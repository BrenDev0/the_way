from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
        str_min_length=2,
    )


class ErrorResponse(ApiBaseModel):
    message: str
    code: str
