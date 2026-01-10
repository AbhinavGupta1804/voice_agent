"""Routes for analytics APIs."""
import logging
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..db.postgres import get_db_pool

logger = logging.getLogger(__name__)


# ============ Response Models ============

class AnalyticsOverview(BaseModel):
    """Overview statistics for analytics dashboard."""
    total_calls: int
    avg_duration_sec: float
    conversion_rate: float
    sentiment_score: float
    total_calls_change: float = Field(default=0.0, description="Percentage change from previous period")
    avg_duration_change: float = Field(default=0.0, description="Percentage change from previous period")
    conversion_rate_change: float = Field(default=0.0, description="Percentage change from previous period")
    sentiment_change: float = Field(default=0.0, description="Percentage change from previous period")


class CallsOverTimeData(BaseModel):
    """Calls per time period."""
    date: str
    calls: int


class ConversionRateData(BaseModel):
    """Conversion rate trend data."""
    date: str
    rate: float


class CallDurationData(BaseModel):
    """Call duration distribution."""
    range: str
    count: int


class InquiryTypeData(BaseModel):
    """Inquiry type breakdown."""
    name: str
    value: int
    color: str


class FollowUpStatusData(BaseModel):
    """Follow-up status by month."""
    month: str
    scheduled: int
    completed: int
    missed: int


class FunnelData(BaseModel):
    """Conversion funnel data."""
    name: str
    value: int
    fill: str


class SentimentData(BaseModel):
    """Sentiment score per call."""
    call_id: str
    score: int


class AnalyticsResponse(BaseModel):
    """Complete analytics data response."""
    overview: AnalyticsOverview
    calls_over_time: List[CallsOverTimeData]
    conversion_rate_trend: List[ConversionRateData]
    call_duration_distribution: List[CallDurationData]
    inquiry_types: List[InquiryTypeData]
    follow_up_status: List[FollowUpStatusData]
    conversion_funnel: List[FunnelData]
    sentiment_scores: List[SentimentData]


# ============ Analytics Service ============

class AnalyticsService:
    """Service for computing analytics from call records."""
    
    @staticmethod
    def _get_period_dates(period: str) -> tuple[datetime, datetime]:
        """Get start and end dates for the specified period."""
        now = datetime.now(timezone.utc)
        
        if period == "week":
            start = now - timedelta(days=7)
        elif period == "month":
            start = now - timedelta(days=30)
        elif period == "quarter":
            start = now - timedelta(days=90)
        elif period == "year":
            start = now - timedelta(days=365)
        else:
            start = now - timedelta(days=7)
        
        return start, now
    
    @staticmethod
    async def get_overview(period: str = "week") -> AnalyticsOverview:
        """Compute overview statistics."""
        pool = await get_db_pool()
        start_date, end_date = AnalyticsService._get_period_dates(period)
        
        # Calculate period duration for previous period
        period_duration = end_date - start_date
        prev_start = start_date - period_duration
        
        try:
            async with pool.acquire() as conn:
                # Current period stats
                total_calls = await conn.fetchval("""
                    SELECT COUNT(*) FROM calls 
                    WHERE call_timestamp >= $1 AND call_timestamp <= $2
                """, start_date, end_date)
                
                conversions = await conn.fetchval("""
                    SELECT COUNT(*) FROM calls 
                    WHERE call_timestamp >= $1 AND call_timestamp <= $2 
                    AND conversion_status = TRUE
                """, start_date, end_date)
                
                avg_duration = await conn.fetchval("""
                    SELECT COALESCE(AVG(duration_sec), 0) FROM calls 
                    WHERE call_timestamp >= $1 AND call_timestamp <= $2
                """, start_date, end_date) or 0
                
                # Previous period stats
                prev_total = await conn.fetchval("""
                    SELECT COUNT(*) FROM calls 
                    WHERE call_timestamp >= $1 AND call_timestamp < $2
                """, prev_start, start_date)
                
                prev_conversions = await conn.fetchval("""
                    SELECT COUNT(*) FROM calls 
                    WHERE call_timestamp >= $1 AND call_timestamp < $2 
                    AND conversion_status = TRUE
                """, prev_start, start_date)
                
                prev_avg_duration = await conn.fetchval("""
                    SELECT COALESCE(AVG(duration_sec), 0) FROM calls 
                    WHERE call_timestamp >= $1 AND call_timestamp < $2
                """, prev_start, start_date) or 0
                
                # Calculate changes
                def calc_change(current: float, previous: float) -> float:
                    if previous == 0:
                        return 100.0 if current > 0 else 0.0
                    return round(((current - previous) / previous) * 100, 1)
                
                conversion_rate = (conversions / total_calls * 100) if total_calls > 0 else 0
                prev_conversion_rate = (prev_conversions / prev_total * 100) if prev_total > 0 else 0
                
                # Sentiment score (placeholder)
                sentiment_score = 75.0
                
                return AnalyticsOverview(
                    total_calls=total_calls,
                    avg_duration_sec=round(avg_duration, 1),
                    conversion_rate=round(conversion_rate, 1),
                    sentiment_score=sentiment_score,
                    total_calls_change=calc_change(total_calls, prev_total),
                    avg_duration_change=calc_change(avg_duration, prev_avg_duration),
                    conversion_rate_change=calc_change(conversion_rate, prev_conversion_rate),
                    sentiment_change=0.0
                )
        except Exception as exc:
            logger.error(f"[Analytics] Get overview failed: {exc}")
            raise
    
    @staticmethod
    async def get_calls_over_time(period: str = "week") -> List[CallsOverTimeData]:
        """Get calls count per day/week/month."""
        pool = await get_db_pool()
        start_date, end_date = AnalyticsService._get_period_dates(period)
        
        try:
            async with pool.acquire() as conn:
                if period == "week":
                    # Group by day of week
                    rows = await conn.fetch("""
                        SELECT TO_CHAR(call_timestamp, 'Dy') as date, COUNT(*) as calls
                        FROM calls
                        WHERE call_timestamp >= $1 AND call_timestamp <= $2
                        GROUP BY TO_CHAR(call_timestamp, 'Dy'), EXTRACT(DOW FROM call_timestamp)
                        ORDER BY EXTRACT(DOW FROM call_timestamp)
                    """, start_date, end_date)
                elif period == "month":
                    # Group by day of month
                    rows = await conn.fetch("""
                        SELECT TO_CHAR(call_timestamp, 'Mon DD') as date, COUNT(*) as calls
                        FROM calls
                        WHERE call_timestamp >= $1 AND call_timestamp <= $2
                        GROUP BY TO_CHAR(call_timestamp, 'Mon DD'), call_timestamp::date
                        ORDER BY call_timestamp::date
                    """, start_date, end_date)
                else:
                    # Group by month
                    rows = await conn.fetch("""
                        SELECT TO_CHAR(call_timestamp, 'Mon') as date, COUNT(*) as calls
                        FROM calls
                        WHERE call_timestamp >= $1 AND call_timestamp <= $2
                        GROUP BY TO_CHAR(call_timestamp, 'Mon'), EXTRACT(MONTH FROM call_timestamp)
                        ORDER BY EXTRACT(MONTH FROM call_timestamp)
                    """, start_date, end_date)
                
                return [
                    CallsOverTimeData(date=row["date"], calls=row["calls"])
                    for row in rows
                ]
        except Exception as exc:
            logger.error(f"[Analytics] Get calls over time failed: {exc}")
            raise
    
    @staticmethod
    async def get_conversion_rate_trend(period: str = "week") -> List[ConversionRateData]:
        """Get conversion rate trend over time."""
        pool = await get_db_pool()
        start_date, end_date = AnalyticsService._get_period_dates(period)
        
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT 
                        EXTRACT(WEEK FROM call_timestamp) as week_num,
                        COUNT(*) as total,
                        SUM(CASE WHEN conversion_status THEN 1 ELSE 0 END) as conversions
                    FROM calls
                    WHERE call_timestamp >= $1 AND call_timestamp <= $2
                    GROUP BY EXTRACT(WEEK FROM call_timestamp)
                    ORDER BY week_num
                """, start_date, end_date)
                
                return [
                    ConversionRateData(
                        date=f"Week {row['week_num']}",
                        rate=round((row["conversions"] / row["total"] * 100) if row["total"] > 0 else 0, 1)
                    )
                    for row in rows
                ]
        except Exception as exc:
            logger.error(f"[Analytics] Get conversion rate trend failed: {exc}")
            raise
    
    @staticmethod
    async def get_call_duration_distribution() -> List[CallDurationData]:
        """Get distribution of call durations."""
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    WITH duration_ranges AS (
                        SELECT 
                            CASE
                                WHEN duration_sec < 120 THEN '0-2min'
                                WHEN duration_sec < 300 THEN '2-5min'
                                WHEN duration_sec < 600 THEN '5-10min'
                                WHEN duration_sec < 900 THEN '10-15min'
                                ELSE '15+min'
                            END as duration_range
                        FROM calls
                        WHERE duration_sec IS NOT NULL
                    )
                    SELECT 
                        duration_range as range,
                        COUNT(*) as count
                    FROM duration_ranges
                    GROUP BY duration_range
                    ORDER BY 
                        CASE duration_range
                            WHEN '0-2min' THEN 1
                            WHEN '2-5min' THEN 2
                            WHEN '5-10min' THEN 3
                            WHEN '10-15min' THEN 4
                            ELSE 5
                        END
                """)
                
                return [
                    CallDurationData(range=row["range"], count=row["count"])
                    for row in rows
                ]
        except Exception as exc:
            logger.error(f"[Analytics] Get duration distribution failed: {exc}")
            raise
    
    @staticmethod
    async def get_inquiry_types() -> List[InquiryTypeData]:
        """Get breakdown of inquiry types from call topics."""
        pool = await get_db_pool()
        
        colors = [
            "hsl(220, 70%, 50%)",
            "hsl(160, 60%, 45%)",
            "hsl(30, 80%, 55%)",
            "hsl(280, 65%, 60%)",
            "hsl(0, 70%, 50%)",
            "hsl(45, 80%, 50%)",
            "hsl(190, 70%, 45%)",
            "hsl(320, 60%, 55%)",
        ]
        
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT topic as name, COUNT(*) as value
                    FROM call_topics
                    GROUP BY topic
                    ORDER BY value DESC
                    LIMIT 10
                """)
                
                return [
                    InquiryTypeData(
                        name=row["name"] or "Other",
                        value=row["value"],
                        color=colors[i % len(colors)]
                    )
                    for i, row in enumerate(rows)
                ]
        except Exception as exc:
            logger.error(f"[Analytics] Get inquiry types failed: {exc}")
            raise
    
    @staticmethod
    async def get_follow_up_status() -> List[FollowUpStatusData]:
        """Get follow-up status by month."""
        pool = await get_db_pool()
        
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", 
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT 
                        EXTRACT(MONTH FROM call_timestamp) as month_num,
                        COUNT(*) as total,
                        SUM(CASE WHEN follow_up_date IS NOT NULL THEN 1 ELSE 0 END) as scheduled,
                        SUM(CASE WHEN conversion_status THEN 1 ELSE 0 END) as completed
                    FROM calls
                    GROUP BY EXTRACT(MONTH FROM call_timestamp)
                    ORDER BY month_num
                """)
                
                return [
                    FollowUpStatusData(
                        month=months[int(row["month_num"]) - 1] if row["month_num"] else "Unknown",
                        scheduled=row["scheduled"],
                        completed=row["completed"],
                        missed=row["total"] - row["scheduled"] - row["completed"]
                    )
                    for row in rows
                ]
        except Exception as exc:
            logger.error(f"[Analytics] Get follow up status failed: {exc}")
            raise
    
    @staticmethod
    async def get_conversion_funnel() -> List[FunnelData]:
        """Get conversion funnel data."""
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
                total_calls = await conn.fetchval("SELECT COUNT(*) FROM calls")
                engaged = await conn.fetchval("SELECT COUNT(*) FROM calls WHERE duration_sec > 30")
                qualified = await conn.fetchval("SELECT COUNT(*) FROM calls WHERE duration_sec > 120")
                converted = await conn.fetchval("SELECT COUNT(*) FROM calls WHERE conversion_status = TRUE")
                
                return [
                    FunnelData(name="Calls", value=total_calls, fill="hsl(220, 70%, 50%)"),
                    FunnelData(name="Engaged", value=engaged, fill="hsl(220, 60%, 55%)"),
                    FunnelData(name="Qualified", value=qualified, fill="hsl(220, 50%, 60%)"),
                    FunnelData(name="Converted", value=converted, fill="hsl(160, 60%, 45%)"),
                ]
        except Exception as exc:
            logger.error(f"[Analytics] Get conversion funnel failed: {exc}")
            raise
    
    @staticmethod
    async def get_sentiment_scores(limit: int = 10) -> List[SentimentData]:
        """Get sentiment scores for recent calls."""
        pool = await get_db_pool()
        
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT call_id, conversion_status, duration_sec, summary
                    FROM calls
                    ORDER BY call_timestamp DESC
                    LIMIT $1
                """, limit)
                
                results = []
                for row in rows:
                    score = 50  # Base score
                    
                    if row["conversion_status"]:
                        score += 30
                    
                    duration = row["duration_sec"] or 0
                    if duration > 300:
                        score += 15
                    elif duration > 120:
                        score += 10
                    elif duration > 60:
                        score += 5
                    
                    score = min(score, 100)
                    
                    results.append(SentimentData(
                        call_id=row["call_id"] or "Unknown",
                        score=score
                    ))
                
                return results
        except Exception as exc:
            logger.error(f"[Analytics] Get sentiment scores failed: {exc}")
            raise


# ============ Route Registration ============

def register_analytics_routes(app):
    """Register analytics REST endpoints."""
    router = APIRouter(tags=["Analytics"])
    
    @router.get("/api/analytics", response_model=AnalyticsResponse)
    async def get_analytics(
        period: str = Query("week", regex="^(week|month|quarter|year)$")
    ):
        """
        Get comprehensive analytics data for the dashboard.
        
        Args:
            period: Time period for analytics (week, month, quarter, year)
        
        Returns:
            Complete analytics data including overview, trends, and distributions
        """
        logger.info(f"[Analytics] Fetching analytics for period: {period}")
        
        # Fetch all analytics data in parallel
        overview = await AnalyticsService.get_overview(period)
        calls_over_time = await AnalyticsService.get_calls_over_time(period)
        conversion_rate_trend = await AnalyticsService.get_conversion_rate_trend(period)
        call_duration_distribution = await AnalyticsService.get_call_duration_distribution()
        inquiry_types = await AnalyticsService.get_inquiry_types()
        follow_up_status = await AnalyticsService.get_follow_up_status()
        conversion_funnel = await AnalyticsService.get_conversion_funnel()
        sentiment_scores = await AnalyticsService.get_sentiment_scores()
        
        return AnalyticsResponse(
            overview=overview,
            calls_over_time=calls_over_time,
            conversion_rate_trend=conversion_rate_trend,
            call_duration_distribution=call_duration_distribution,
            inquiry_types=inquiry_types,
            follow_up_status=follow_up_status,
            conversion_funnel=conversion_funnel,
            sentiment_scores=sentiment_scores
        )
    
    @router.get("/api/analytics/overview", response_model=AnalyticsOverview)
    async def get_analytics_overview(
        period: str = Query("week", regex="^(week|month|quarter|year)$")
    ):
        """Get only overview statistics."""
        return await AnalyticsService.get_overview(period)
    
    @router.get("/api/analytics/calls-over-time", response_model=List[CallsOverTimeData])
    async def get_calls_over_time(
        period: str = Query("week", regex="^(week|month|quarter|year)$")
    ):
        """Get calls count over time."""
        return await AnalyticsService.get_calls_over_time(period)
    
    @router.get("/api/analytics/conversion-trend", response_model=List[ConversionRateData])
    async def get_conversion_trend(
        period: str = Query("week", regex="^(week|month|quarter|year)$")
    ):
        """Get conversion rate trend."""
        return await AnalyticsService.get_conversion_rate_trend(period)
    
    @router.get("/api/analytics/duration-distribution", response_model=List[CallDurationData])
    async def get_duration_distribution():
        """Get call duration distribution."""
        return await AnalyticsService.get_call_duration_distribution()
    
    @router.get("/api/analytics/inquiry-types", response_model=List[InquiryTypeData])
    async def get_inquiry_types():
        """Get inquiry types breakdown."""
        return await AnalyticsService.get_inquiry_types()
    
    @router.get("/api/analytics/funnel", response_model=List[FunnelData])
    async def get_funnel():
        """Get conversion funnel data."""
        return await AnalyticsService.get_conversion_funnel()
    
    app.include_router(router)
