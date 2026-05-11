import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..utils.logger import get_logger
from ..utils.security import validate_account_id

logger = get_logger(__name__)

R2_REQUEST_TIMEOUT = 10


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class R2Client:
    def __init__(self, account_id: str, access_key: str, secret_key: str, bucket: str):
        self.bucket = bucket
        self.enabled = bool(account_id and access_key and secret_key)

        if self.enabled:
            if not validate_account_id(account_id):
                logger.warning(
                    "Cloudflare account ID format invalid (expected 32 hex chars) — disabling R2"
                )
                self.enabled = False
                return
            try:
                import boto3
                from botocore.config import Config
                endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
                cfg = Config(
                    connect_timeout=R2_REQUEST_TIMEOUT,
                    read_timeout=R2_REQUEST_TIMEOUT,
                    retries={"max_attempts": 2},
                )
                self._s3 = boto3.client(
                    "s3",
                    endpoint_url=endpoint,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    region_name="auto",
                    config=cfg,
                )
                logger.info("Cloudflare R2 storage connected")
            except Exception as e:
                logger.warning(f"R2 init failed, disabling cloud storage: {e}")
                self.enabled = False
        else:
            logger.info("R2 not configured — trade logs will be local only")

    def _put(self, key: str, data: Dict) -> bool:
        if not self.enabled:
            return False
        try:
            self._s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(data, default=str),
                ContentType="application/json",
            )
            return True
        except Exception as e:
            logger.error(f"R2 upload failed ({key}): {e}")
            return False

    def log_trade(self, trade: Dict[str, Any]) -> bool:
        now = _utcnow()
        date = now.strftime("%Y/%m/%d")
        ts = now.strftime("%H%M%S%f")
        symbol = trade.get("symbol", "unknown")
        return self._put(f"trades/{date}/{ts}_{symbol}.json", trade)

    def log_decision(self, decision: Dict[str, Any]) -> bool:
        now = _utcnow()
        date = now.strftime("%Y/%m/%d")
        ts = now.strftime("%H%M%S%f")
        return self._put(f"decisions/{date}/{ts}.json", decision)

    def get_trade_history(self) -> List[Dict]:
        if not self.enabled:
            return []
        try:
            trades = []
            paginator = self._s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix="trades/"):
                for obj in page.get("Contents", []):
                    content = self._s3.get_object(Bucket=self.bucket, Key=obj["Key"])
                    trades.append(json.loads(content["Body"].read()))
            return trades
        except Exception as e:
            logger.error(f"R2 history fetch failed: {e}")
            return []
