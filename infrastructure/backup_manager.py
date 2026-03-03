import asyncio
import json
import logging
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional, List, Dict


class BackupManager:
    """
    Система бэкапов с автоматическим восстановлением
    """

    def __init__(self, db_path: str, backup_dir: str = "backups"):
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)

        self.auto_backup_interval = 3600  # 1 час
        self.max_backups = 168  # 7 дней
        self.last_backup_time = 0

    async def create_backup(self, backup_type: str = "auto") -> Optional[Path]:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"backup_{backup_type}_{timestamp}"
            backup_path.mkdir(exist_ok=True)

            # --- DB ---
            if self.db_path.exists():
                import shutil
                shutil.copy2(
                    self.db_path,
                    backup_path / self.db_path.name
                )

            # --- LOG ---
            log_file = Path("trading_bot.log")
            if log_file.exists():
                import shutil
                shutil.copy2(log_file, backup_path / log_file.name)

            # --- METADATA ---
            metadata = {
                "timestamp": datetime.now(UTC).isoformat(),
                "backup_type": backup_type,
                "files": [],
            }

            for file in backup_path.iterdir():
                if file.is_file():
                    metadata["files"].append({
                        "name": file.name,
                        "size": file.stat().st_size,
                        "modified": datetime.fromtimestamp(
                            file.stat().st_mtime
                        ).isoformat(),
                    })

            with open(
                backup_path / "metadata.json", "w", encoding="utf-8"
            ) as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            self.last_backup_time = time.time()
            await self._cleanup_old_backups()

            logging.info(f"✅ Backup created: {backup_path.name}")
            return backup_path

        except Exception as e:
            logging.error(f"❌ Backup failed: {e}")
            return None

    async def _cleanup_old_backups(self):
        try:
            import shutil

            backups = sorted(
                [b for b in self.backup_dir.iterdir() if b.is_dir()],
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )

            for old in backups[self.max_backups:]:
                shutil.rmtree(old)
                logging.info(f"🗑️ Removed old backup: {old.name}")

        except Exception as e:
            logging.error(f"Backup cleanup error: {e}")

    async def restore(self, backup_name: str) -> bool:
        try:
            backup_path = self.backup_dir / backup_name
            if not backup_path.exists():
                return False

            await self.create_backup("pre_restore")

            db_backup = backup_path / self.db_path.name
            if db_backup.exists():
                import shutil
                shutil.copy2(db_backup, self.db_path)

            logging.info(f"✅ Restored backup: {backup_name}")
            return True

        except Exception as e:
            logging.error(f"❌ Restore failed: {e}")
            return False

    def list_backups(self) -> List[Dict]:
        backups = []

        for b in sorted(
            self.backup_dir.iterdir(),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        ):
            meta = b / "metadata.json"
            if not meta.exists():
                continue

            try:
                with open(meta, "r", encoding="utf-8") as f:
                    data = json.load(f)

                size_mb = sum(
                    f.stat().st_size for f in b.iterdir() if f.is_file()
                ) / (1024 * 1024)

                backups.append({
                    "name": b.name,
                    "timestamp": data.get("timestamp"),
                    "type": data.get("backup_type"),
                    "size_mb": round(size_mb, 2),
                })
            except Exception:
                pass

        return backups

    async def auto_backup_loop(self):
        while True:
            try:
                await asyncio.sleep(self.auto_backup_interval / 2)

                if time.time() - self.last_backup_time >= self.auto_backup_interval:
                    await self.create_backup("auto")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Auto backup error: {e}")
