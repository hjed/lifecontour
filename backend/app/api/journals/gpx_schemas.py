"""GPX-specific API schemas for parsed track data responses.

Defines Pydantic models for the GPX track data endpoint that serves
parsed coordinates and computed statistics to the frontend.
"""

from pydantic import BaseModel, Field


class GPXCoordinateSchema(BaseModel):
    """A single coordinate point from a GPX track."""

    latitude: float = Field(..., description="Latitude in decimal degrees")
    longitude: float = Field(..., description="Longitude in decimal degrees")
    elevation: float | None = Field(default=None, description="Elevation in metres")


class GPXStatisticsSchema(BaseModel):
    """Computed statistics from a GPX track."""

    distance_2d: float = Field(..., description="Horizontal distance in metres", ge=0)
    distance_3d: float = Field(
        ..., description="Distance accounting for elevation in metres", ge=0
    )
    elevation_gain: float = Field(..., description="Total uphill metres", ge=0)
    elevation_loss: float = Field(
        ..., description="Total downhill metres (positive value)", ge=0
    )
    duration_seconds: float | None = Field(
        default=None,
        description="Total track duration in seconds (null if no timestamps)",
    )


class GPXTrackDataAttributes(BaseModel):
    """Attributes for the GPX track data resource."""

    coordinates: list[GPXCoordinateSchema] = Field(
        ..., description="Ordered list of track points"
    )
    statistics: GPXStatisticsSchema = Field(
        ..., description="Computed distance, elevation, and duration statistics"
    )


class GPXTrackDataResource(BaseModel):
    """GPX track data resource following JSON API specification."""

    type: str = Field(default="gpx-track-data", description="Resource type")
    id: str = Field(..., description="Journal ID")
    attributes: GPXTrackDataAttributes = Field(
        ..., description="GPX track data attributes"
    )


class GPXTrackDataResponse(BaseModel):
    """Response model for GPX track data."""

    data: GPXTrackDataResource = Field(..., description="GPX track data resource")
