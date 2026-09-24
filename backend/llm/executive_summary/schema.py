from typing import List, Optional
from pydantic import BaseModel, Field


class ExtractedItem(BaseModel):
    text: str = Field(..., description="Factual statement or requirement extracted from the text.")
    page: int = Field(..., description="Page number where this information appears.")


class PassAInformation(BaseModel):
    overview: List[ExtractedItem] = Field(default_factory=list)
    scope: List[ExtractedItem] = Field(default_factory=list)
    requirements: List[ExtractedItem] = Field(default_factory=list)
    eligibility: List[ExtractedItem] = Field(default_factory=list)


class PassBInformation(BaseModel):
    important_dates: List[ExtractedItem] = Field(default_factory=list)
    commercial_requirements: List[ExtractedItem] = Field(default_factory=list)
    project_duration: List[ExtractedItem] = Field(default_factory=list)
    important_conditions: List[ExtractedItem] = Field(default_factory=list)


class ChunkInformation(BaseModel):
    overview: List[ExtractedItem] = Field(default_factory=list)
    scope: List[ExtractedItem] = Field(default_factory=list)
    requirements: List[ExtractedItem] = Field(default_factory=list)
    eligibility: List[ExtractedItem] = Field(default_factory=list)
    important_dates: List[ExtractedItem] = Field(default_factory=list)
    commercial_requirements: List[ExtractedItem] = Field(default_factory=list)
    project_duration: List[ExtractedItem] = Field(default_factory=list)
    important_conditions: List[ExtractedItem] = Field(default_factory=list)


class ChunkAnalysisResult(BaseModel):
    chunk_id: int
    pages: List[int]
    word_count: int
    pass_a_success: bool = True
    pass_b_success: bool = True
    pass_a_error: Optional[str] = None
    pass_b_error: Optional[str] = None
    pass_a_inference_time_seconds: float = 0.0
    pass_b_inference_time_seconds: float = 0.0
    total_inference_time_seconds: float = 0.0
    information: ChunkInformation


class AggregatedItem(BaseModel):
    text: str = Field(..., description="Summary statement.")
    pages: List[int] = Field(default_factory=list, description="Source page numbers.")


class ExecutiveSummaryOutput(BaseModel):
    overview: AggregatedItem = Field(..., description="Traceable overview statement.")
    issuing_organization: str = Field(..., description="Issuing organization name.")
    scope: List[AggregatedItem] = Field(default_factory=list)
    key_requirements: List[AggregatedItem] = Field(default_factory=list)
    eligibility: List[AggregatedItem] = Field(default_factory=list)
    important_dates: List[AggregatedItem] = Field(default_factory=list)
    commercial_requirements: List[AggregatedItem] = Field(default_factory=list)
    project_duration: List[AggregatedItem] = Field(default_factory=list)
    important_conditions: List[AggregatedItem] = Field(default_factory=list)


class DocumentAnalysisResult(BaseModel):
    document_name: str
    total_chunks: int
    total_pass_a_inference_time_seconds: float
    total_pass_b_inference_time_seconds: float
    total_inference_time_seconds: float
    chunks: List[ChunkAnalysisResult]
