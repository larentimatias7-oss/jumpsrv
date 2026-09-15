from __future__ import annotations
import logging
from typing import Any, List, Dict, Optional
from sqlalchemy.orm import Session

from ..models.database import CategoryModel, KioskModel
from ..jumpserver.client import JumpServerClient
from ..jumpserver.config import get_jms_settings

logger = logging.getLogger("kiosk.category_service")


class CategoryService:
    """Manages Category lifecycle and synchronizes dynamically with JumpServer Nodes tree."""

    def __init__(self, jms_client: Optional[JumpServerClient] = None):
        self.config = get_jms_settings()
        self.jms_client = jms_client or JumpServerClient(self.config)
        self.default_node_name = getattr(self.config, "default_node_name", "SWITCHES ROSARIO")

    def list_categories(self, session: Session) -> List[Dict[str, Any]]:
        """List all categories with device counts."""
        categories = session.query(CategoryModel).order_by(CategoryModel.name).all()
        out = []
        for cat in categories:
            device_count = session.query(KioskModel).filter(
                (KioskModel.category_id == cat.id) | (KioskModel.category_name == cat.name)
            ).count()
            out.append({
                "id": cat.id,
                "name": cat.name,
                "description": cat.description or "",
                "jms_node_id": cat.jms_node_id,
                "icon": cat.icon or "📁",
                "device_count": device_count,
                "created_at": cat.created_at.isoformat() if cat.created_at else None,
                "updated_at": cat.updated_at.isoformat() if cat.updated_at else None,
            })
        return out

    def get_category_by_id(self, session: Session, category_id: str) -> Optional[CategoryModel]:
        return session.query(CategoryModel).filter(CategoryModel.id == category_id).first()

    def get_category_by_name(self, session: Session, name: str) -> Optional[CategoryModel]:
        return session.query(CategoryModel).filter(CategoryModel.name.ilike(name.strip())).first()

    def create_category(
        self,
        session: Session,
        name: str,
        description: Optional[str] = None,
        icon: str = "📁",
    ) -> Dict[str, Any]:
        """Create category locally and ensure corresponding node in JumpServer."""
        clean_name = name.strip().upper()
        existing = session.query(CategoryModel).filter(CategoryModel.name == clean_name).first()
        if existing:
            raise ValueError(f"Category '{clean_name}' already exists.")

        # Ensure node exists in JumpServer (creates dynamically if needed)
        jms_node_id = None
        try:
            jms_node_id = self.jms_client.ensure_node(clean_name)
            logger.info("Ensured JumpServer node for category '%s': %s", clean_name, jms_node_id)
        except Exception as e:
            logger.warning("Could not ensure node in JumpServer for category '%s': %s", clean_name, e)

        category = CategoryModel(
            name=clean_name,
            description=description,
            jms_node_id=jms_node_id,
            icon=icon or "📁",
        )
        session.add(category)
        session.commit()
        session.refresh(category)

        return {
            "id": category.id,
            "name": category.name,
            "description": category.description,
            "jms_node_id": category.jms_node_id,
            "icon": category.icon,
            "device_count": 0,
            "created_at": category.created_at.isoformat() if category.created_at else None,
        }

    def update_category(
        self,
        session: Session,
        category_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update category and propagate rename to JumpServer node and kiosks."""
        cat = self.get_category_by_id(session, category_id)
        if not cat:
            raise ValueError(f"Category with ID '{category_id}' not found.")

        old_name = cat.name
        new_name = name.strip().upper() if name else old_name

        if new_name != old_name:
            duplicate = session.query(CategoryModel).filter(
                CategoryModel.name == new_name,
                CategoryModel.id != category_id
            ).first()
            if duplicate:
                raise ValueError(f"Category with name '{new_name}' already exists.")

            # Propagate name change to JumpServer
            new_node_id = None
            if cat.jms_node_id:
                try:
                    self.jms_client.patch(f"/api/v1/assets/nodes/{cat.jms_node_id}/", {"value": new_name})
                    new_node_id = cat.jms_node_id
                    logger.info("Updated JumpServer node %s to '%s'", cat.jms_node_id, new_name)
                except Exception as patch_err:
                    logger.warning("PATCH node failed, falling back to ensure_node: %s", patch_err)
                    try:
                        new_node_id = self.jms_client.ensure_node(new_name)
                    except Exception as ens_err:
                        logger.warning("ensure_node failed during rename: %s", ens_err)
            else:
                try:
                    new_node_id = self.jms_client.ensure_node(new_name)
                except Exception as ens_err:
                    logger.warning("ensure_node failed: %s", ens_err)

            cat.name = new_name
            if new_node_id:
                cat.jms_node_id = new_node_id

            # Update associated kiosks
            kiosks = session.query(KioskModel).filter(
                (KioskModel.category_id == category_id) | (KioskModel.category_name == old_name)
            ).all()
            for k in kiosks:
                k.category_name = new_name
                k.jms_node_name = new_name
                if new_node_id:
                    k.jms_node_id = new_node_id

        if description is not None:
            cat.description = description
        if icon is not None:
            cat.icon = icon

        session.commit()
        session.refresh(cat)

        device_count = session.query(KioskModel).filter(
            (KioskModel.category_id == cat.id) | (KioskModel.category_name == cat.name)
        ).count()

        return {
            "id": cat.id,
            "name": cat.name,
            "description": cat.description,
            "jms_node_id": cat.jms_node_id,
            "icon": cat.icon,
            "device_count": device_count,
            "updated_at": cat.updated_at.isoformat() if cat.updated_at else None,
        }

    def delete_category(
        self,
        session: Session,
        category_id: str,
        reassign_to_default: bool = True,
    ) -> Dict[str, Any]:
        """Delete category safely; reassign orphans to default node and delete JMS node safely."""
        cat = self.get_category_by_id(session, category_id)
        if not cat:
            raise ValueError(f"Category with ID '{category_id}' not found.")

        # Reassign orphan kiosks
        kiosks = session.query(KioskModel).filter(
            (KioskModel.category_id == category_id) | (KioskModel.category_name == cat.name)
        ).all()
        reassigned_count = len(kiosks)
        if kiosks and reassign_to_default:
            logger.warning(
                "Category '%s' has %d associated kiosks. Reassigning to default node '%s'.",
                cat.name, reassigned_count, self.default_node_name,
            )
            default_node_id = None
            try:
                default_node_id = self.jms_client.ensure_node(self.default_node_name)
            except Exception as e:
                logger.warning("Could not ensure default node '%s': %s", self.default_node_name, e)

            for k in kiosks:
                k.category_id = None
                k.category_name = self.default_node_name
                k.jms_node_name = self.default_node_name
                if default_node_id:
                    k.jms_node_id = default_node_id

        # Attempt to delete JumpServer node safely
        if cat.jms_node_id:
            try:
                self.jms_client.delete_node(cat.jms_node_id)
            except Exception as del_err:
                logger.warning("Non-blocking error deleting JumpServer node %s: %s", cat.jms_node_id, del_err)

        session.delete(cat)
        session.commit()

        return {
            "status": "deleted",
            "category_id": category_id,
            "reassigned_kiosks": reassigned_count,
            "default_node": self.default_node_name,
        }

    def sync_jms_nodes(self, session: Session) -> Dict[str, Any]:
        """Synchronize JumpServer nodes tree with local categories catalog dynamically."""
        imported_count = 0
        pushed_count = 0

        # 1. Fetch remote nodes from JumpServer
        try:
            remote_nodes = self.jms_client.list_nodes()
        except Exception as e:
            logger.error("Failed to list nodes from JumpServer: %s", e)
            remote_nodes = []

        # 2. Import nodes from JumpServer to local categories
        for node in remote_nodes:
            if not isinstance(node, dict):
                continue
            val = str(node.get("value") or node.get("name") or "").strip().upper()
            node_id = node.get("id")
            if not val or val in ("DEFAULT", "/", "ROOT"):
                continue

            existing = session.query(CategoryModel).filter(CategoryModel.name == val).first()
            if not existing:
                cat = CategoryModel(
                    name=val,
                    description=f"Sincronizado desde JumpServer ({node_id})",
                    jms_node_id=str(node_id) if node_id else None,
                    icon="📁",
                )
                session.add(cat)
                imported_count += 1
            else:
                if node_id and existing.jms_node_id != str(node_id):
                    existing.jms_node_id = str(node_id)

        session.commit()

        # 3. Ensure local categories without node ID exist in JumpServer
        local_categories = session.query(CategoryModel).all()
        for cat in local_categories:
            if not cat.jms_node_id:
                try:
                    node_id = self.jms_client.ensure_node(cat.name)
                    if node_id:
                        cat.jms_node_id = node_id
                        pushed_count += 1
                except Exception as e:
                    logger.warning("Failed to push category '%s' to JumpServer: %s", cat.name, e)

        # 4. Also ensure default node exists
        try:
            self.jms_client.ensure_node(self.default_node_name)
        except Exception:
            pass

        session.commit()

        total = session.query(CategoryModel).count()
        return {
            "status": "synchronized",
            "total_categories": total,
            "imported_from_jms": imported_count,
            "pushed_to_jms": pushed_count,
            "default_node": self.default_node_name,
        }
