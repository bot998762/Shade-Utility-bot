from aiohttp import web

async def health_check_handler(request):
    ""';"Dedicated health check endpoint for Render monitoring"""
    return web.json_response({
        "status": "healthy",
        "service": "Shade Utility Platform V8",
        "uptime_status": "operational"
    }, status=200)
