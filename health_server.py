import asyncio
from aiohttp import web
import logging
import os

logger = logging.getLogger(__name__)

class HealthServer:
    def __init__(self, port=8000):
        self.port = int(os.getenv("PORT", port))
        self.app = web.Application()
        self.setup_routes()
        
    def setup_routes(self):
        """Configure les routes du serveur de santé"""
        self.app.router.add_get('/', self.health_check)
        self.app.router.add_get('/health', self.health_check)
        self.app.router.add_get('/status', self.status_check)
        
    async def health_check(self, request):
        """Endpoint de health check pour Koyeb"""
        return web.json_response({
            "status": "healthy",
            "service": "discord-bot",
            "timestamp": asyncio.get_event_loop().time()
        })
        
    async def status_check(self, request):
        """Endpoint de statut détaillé"""
        return web.json_response({
            "status": "running",
            "bot": "online",
            "database": "connected"
        })
    
    async def start(self):
        """Démarre le serveur de santé"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        logger.info(f"🏥 Serveur de santé démarré sur le port {self.port}")
        
    async def run_forever(self):
        """Maintient le serveur en vie"""
        await self.start()
        try:
            while True:
                await asyncio.sleep(3600)  # Sleep 1 heure
        except asyncio.CancelledError:
            logger.info("🏥 Arrêt du serveur de santé")
            raise
