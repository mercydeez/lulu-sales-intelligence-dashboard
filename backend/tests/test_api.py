# API and SSE Testing Script for Lulu Intelligence Dashboard
# Run this script to verify all endpoints are working properly

import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import Optional

BASE_URL = "http://localhost:8000"
TEST_USER = {"username": "yash@lulu.ae", "password": "Lulu@2026!"}

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def success(msg: str) -> str:
    return f"{Colors.GREEN}✓{Colors.RESET} {msg}"

def failure(msg: str) -> str:
    return f"{Colors.RED}✗{Colors.RESET} {msg}"

def warning(msg: str) -> str:
    return f"{Colors.YELLOW}⚠{Colors.RESET} {msg}"

def info(msg: str) -> str:
    return f"{Colors.CYAN}ℹ{Colors.RESET} {msg}"

def header(msg: str) -> str:
    return f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}\n{msg}\n{'='*60}{Colors.RESET}"

class APITester:
    def __init__(self):
        self.token: Optional[str] = None
        self.results = {"passed": 0, "failed": 0, "warnings": 0}
        
    async def authenticate(self, session: aiohttp.ClientSession) -> bool:
        """Authenticate and get JWT token"""
        try:
            async with session.post(
                f"{BASE_URL}/api/auth/login",
                data=TEST_USER,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.token = data.get("access_token")
                    print(success(f"Authentication successful for {TEST_USER['username']}"))
                    return True
                else:
                    print(failure(f"Authentication failed: {resp.status}"))
                    return False
        except Exception as e:
            print(failure(f"Authentication error: {e}"))
            return False

    def get_headers(self) -> dict:
        """Get headers with auth token"""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def test_endpoint(
        self, 
        session: aiohttp.ClientSession,
        method: str,
        endpoint: str,
        description: str,
        expected_status: int = 200,
        data: dict = None,
        auth_required: bool = True
    ) -> bool:
        """Test a single API endpoint"""
        headers = self.get_headers() if auth_required else {}
        
        try:
            url = f"{BASE_URL}{endpoint}"
            kwargs = {"headers": headers}
            if data:
                kwargs["json"] = data
                
            async with getattr(session, method.lower())(url, **kwargs) as resp:
                response_data = None
                try:
                    response_data = await resp.json()
                except:
                    pass
                
                if resp.status == expected_status:
                    print(success(f"{description} ({endpoint}) - Status: {resp.status}"))
                    self.results["passed"] += 1
                    return True
                else:
                    print(failure(f"{description} ({endpoint}) - Expected: {expected_status}, Got: {resp.status}"))
                    if response_data:
                        print(f"    Response: {json.dumps(response_data, indent=2)[:200]}")
                    self.results["failed"] += 1
                    return False
        except Exception as e:
            print(failure(f"{description} ({endpoint}) - Error: {e}"))
            self.results["failed"] += 1
            return False

    async def test_sse_streaming(self, session: aiohttp.ClientSession) -> bool:
        """Test SSE streaming endpoint"""
        print(info("Testing SSE streaming (will collect 5 events or timeout in 15s)..."))
        
        headers = self.get_headers()
        events_received = []
        start_time = time.time()
        
        try:
            async with session.get(
                f"{BASE_URL}/api/stream",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    print(failure(f"SSE connection failed with status {resp.status}"))
                    self.results["failed"] += 1
                    return False
                
                async for line in resp.content:
                    if time.time() - start_time > 15:
                        break
                        
                    decoded = line.decode('utf-8').strip()
                    if decoded.startswith('data:'):
                        try:
                            data = json.loads(decoded[5:].strip())
                            events_received.append(data)
                            event_type = data.get('type', 'unknown')
                            print(f"    📡 Received: {event_type}")
                            
                            if len(events_received) >= 5:
                                break
                        except json.JSONDecodeError:
                            pass
                            
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(warning(f"SSE test ended with: {e}"))
            
        if events_received:
            print(success(f"SSE streaming working - received {len(events_received)} events"))
            self.results["passed"] += 1
            return True
        else:
            print(warning("SSE streaming - no events received (generator might not be running)"))
            self.results["warnings"] += 1
            return False

    async def run_all_tests(self):
        """Run comprehensive API tests"""
        print(header("LULU INTELLIGENCE DASHBOARD - API TEST SUITE"))
        print(f"Testing against: {BASE_URL}")
        print(f"Timestamp: {datetime.now().isoformat()}\n")
        
        async with aiohttp.ClientSession() as session:
            # 1. Health Checks (No Auth)
            print(header("1. HEALTH CHECK ENDPOINTS"))
            await self.test_endpoint(session, "GET", "/health", "Basic Health Check", auth_required=False)
            
            # 2. Authentication
            print(header("2. AUTHENTICATION"))
            auth_success = await self.authenticate(session)
            if not auth_success:
                print(failure("Cannot continue without authentication"))
                return
            
            # 3. Monitoring Endpoints
            print(header("3. MONITORING ENDPOINTS"))
            await self.test_endpoint(session, "GET", "/api/monitoring/health/detailed", "Detailed Health")
            await self.test_endpoint(session, "GET", "/api/monitoring/ready", "Readiness Check")
            await self.test_endpoint(session, "GET", "/api/monitoring/live", "Liveness Check")
            await self.test_endpoint(session, "GET", "/api/monitoring/stats", "System Stats")
            await self.test_endpoint(session, "GET", "/api/monitoring/metrics/json", "Metrics JSON")
            
            # 4. Sales API
            print(header("4. SALES API ENDPOINTS"))
            await self.test_endpoint(session, "GET", "/api/sales/", "Get Sales (default)")
            await self.test_endpoint(session, "GET", "/api/sales/?limit=10", "Get Sales (limited)")
            await self.test_endpoint(session, "GET", "/api/sales/stats", "Sales Statistics")
            await self.test_endpoint(session, "GET", "/api/sales/streaming", "Streaming Sales")
            
            # 5. KPIs
            print(header("5. KPI ENDPOINTS"))
            await self.test_endpoint(session, "GET", "/api/kpis/", "Get KPIs")
            await self.test_endpoint(session, "GET", "/api/kpis/live", "Live KPIs")
            
            # 6. Analytics
            print(header("6. ANALYTICS ENDPOINTS"))
            await self.test_endpoint(session, "GET", "/api/analytics/sales-trend", "Sales Trend")
            await self.test_endpoint(session, "GET", "/api/analytics/category-breakdown", "Category Breakdown")
            await self.test_endpoint(session, "GET", "/api/analytics/store-performance", "Store Performance")
            await self.test_endpoint(session, "GET", "/api/analytics/top-items", "Top Items")
            await self.test_endpoint(session, "GET", "/api/analytics/returns", "Returns Analytics")
            
            # 7. AI Endpoints
            print(header("7. AI ASSISTANT ENDPOINTS"))
            await self.test_endpoint(
                session, "POST", "/api/ai/analyze",
                "AI Analysis",
                data={"query": "What are today's sales trends?"}
            )
            await self.test_endpoint(
                session, "POST", "/api/ai/chat",
                "AI Chat",
                data={"message": "Hello", "conversation_history": []}
            )
            await self.test_endpoint(session, "GET", "/api/ai/suggestions", "AI Suggestions")
            
            # 8. History
            print(header("8. HISTORY ENDPOINTS"))
            await self.test_endpoint(session, "GET", "/api/history/", "Query History")
            
            # 9. SSE Streaming
            print(header("9. SSE STREAMING"))
            await self.test_sse_streaming(session)
            
            # Results Summary
            print(header("TEST RESULTS SUMMARY"))
            total = self.results["passed"] + self.results["failed"]
            print(f"  {Colors.GREEN}Passed:{Colors.RESET}   {self.results['passed']}/{total}")
            print(f"  {Colors.RED}Failed:{Colors.RESET}   {self.results['failed']}/{total}")
            print(f"  {Colors.YELLOW}Warnings:{Colors.RESET} {self.results['warnings']}")
            
            if self.results["failed"] == 0:
                print(f"\n{Colors.GREEN}{Colors.BOLD}All tests passed! ✓{Colors.RESET}")
            else:
                print(f"\n{Colors.RED}{Colors.BOLD}Some tests failed. Review the output above.{Colors.RESET}")

async def main():
    tester = APITester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
