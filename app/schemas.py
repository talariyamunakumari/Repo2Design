from pydantic import BaseModel


class ComponentInfo(BaseModel):
    name: str
    responsibility: str


class Architecture(BaseModel):
    summary: str
    data_flow: str
    components: list[ComponentInfo]


class EndpointDesc(BaseModel):
    index: int
    description: str


class EndpointDescList(BaseModel):
    items: list[EndpointDesc]


class QA(BaseModel):
    question: str
    answer: str


class QAList(BaseModel):
    items: list[QA]
