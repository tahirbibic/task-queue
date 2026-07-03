from pydantic import BaseModel, Field, field_validator

class JobCreate(BaseModel):
    task_name: str
    payload: dict = Field(default_factory=dict)

    @field_validator("task_name")
    @classmethod
    def task_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task_name cannot be empty")
        return v