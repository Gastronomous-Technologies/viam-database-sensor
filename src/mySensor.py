from typing import Any, ClassVar, Dict, Mapping, Optional, Sequence, List
from typing_extensions import Self
from viam.components.sensor import Sensor
from viam.logging import getLogger
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.types import Model, ModelFamily
from viam.utils import struct_to_dict, from_dm_from_extra
from viam.errors import NoCaptureToStoreError
from mysql.connector.aio import connect

LOGGER = getLogger(__name__)

class MySensor(Sensor):
    MODEL: ClassVar[Model] = Model(ModelFamily("gastronomous", "db"), "mysql-filter")
    REQUIRED_ATTRIBUTES = ["user", "password", "host", "database"]

    def __init__(self, name: str):
        super().__init__(name)

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        sensor = cls(config.name)
        sensor.reconfigure(config, dependencies)
        return sensor

    @classmethod
    def validate_config(cls, config: dict) -> Sequence[str]:
        missing_attrs = [attr for attr in cls.REQUIRED_ATTRIBUTES if attr not in config['database_config'] or not config['database_config'][attr].strip()]
        if missing_attrs:
            raise ValueError(f"Missing required attributes in database_config: {', '.join(missing_attrs)}")
        return []

    def reconfigure(self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]):
        self.config = struct_to_dict(config.attributes)
        self.database_config = self.config['database_config']
        self.queries = self.config['queries']
        self.table = self.config['table']
        LOGGER.debug("%s is reconfigured", self.name)

    async def get_readings(self, extra: Optional[Dict[str, Any]] = None, **kwargs) -> Mapping[str, Any]:
        if not self.database_config:
            return {"error": "Database credentials are incomplete or missing"}

        if from_dm_from_extra(extra) and 'filter_query' in self.queries and 'action_query' in self.queries:
            results = await self.run_query(self.queries.get('filter_query'))
            if not results:
                raise NoCaptureToStoreError
            await self.run_query(self.queries.get('action_query'))
            return results
        else:
            return await self.run_query(self.queries.get('filter_query'))

    async def run_query(self, query: str) -> Dict[str, Any]:
        async with await connect(**self.database_config) as conn:
            async with await conn.cursor() as cursor:
                await cursor.execute(query)
                if query.lower().startswith("select"):
                    rows = await cursor.fetchall()
                    if not rows:
                        LOGGER.debug("Query returned no rows")
                        await cursor.close()
                        raise NoCaptureToStoreError
                        return {}
                    keys = [column[0] for column in cursor.description]
                    await cursor.close()
                    row = rows[0]
                    readings = {keys[i]: str(row[i]) for i in range(len(row))}
                    return readings
                else:
                    await conn.commit()
                    await cursor.close()
                    return {}
