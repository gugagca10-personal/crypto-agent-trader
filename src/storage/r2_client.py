import json
from datetime import datetime
from typing import Any, Dict, List

from ..utils.logger import get_logger

logger = get_logger(__name__)


class R2Client:
    def __init__(self, account_id: str, access_key: str, secret_key: str, bucket: str):
        self.bucket = bucket
        self.enabled = bool(account_id and access_key and secret_key)

        if self.enabled:
            try:
                import boto3
                endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
                self._s3 = boto3.client(
                    "s3",
                    endpoint_url=endpoint,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    region_name="auto",
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
        date = datetime.utcnow().strftime("%Y/%m/%d")
        ts = datetime.utcnow().strftime("%H%M%S%f")
        symbol = trade.get("symbol", "unknown")
        return self._put(f"trades/{date}/{ts}_{symbol}.json", trade)

    def log_decision(self, decision: Dict[str, Any]) -> bool:
        date = datetime.utcnow().strftime("%Y/%m/%d")
        ts = datetime.utcnow().strftime("%H%M%S%f")
        return self._put(f"decisions/{date}/{ts}.json", decision)

    def get_trade_history(self) -> List[Dict]:
        if not self.enabled:
            return []
        try:
            resp = self._s3.list_objects_v2(Bucket=self.bucket, Prefix="trades/")
            trades = []
            for obj in resp.get("Contents", []):
                content = self._s3.get_object(Bucket=self.bucket, Key=obj["Key"])
                trades.append(json.loads(content["Body"].read()))
            return trades
        except Exception as e:
            logger.error(f"R2 history fetch failed: {e}")
            return []
