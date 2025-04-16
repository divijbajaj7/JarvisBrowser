"""
Playwright browser on steroids.
"""

import asyncio
import gc
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from playwright._impl._api_structures import ProxySettings
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import (
    Playwright,
    async_playwright,
)

from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)


@dataclass
class BrowserConfig:
    r"""
    Configuration for the Browser.

    Default values:
        headless: True
            Whether to run browser in headless mode

        disable_security: True
            Disable browser security features

        extra_chromium_args: []
            Extra arguments to pass to the browser

        wss_url: None
            Connect to a browser instance via WebSocket

        cdp_url: None
            Connect to a browser instance via CDP

        chrome_instance_path: None
            Path to a Chrome instance to use to connect to your normal browser
            e.g. '/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome'
            
        browser_type: 'chromium'
            Browser type to launch: 'chromium', 'firefox', 'webkit', or 'msedge'
            
        user_data_dir: None
            Path to user data directory for persistent sessions
            
        use_existing_browser: False
            Whether to connect to an existing browser instance
    """

    headless: bool = False
    disable_security: bool = True
    extra_chromium_args: list[str] = field(default_factory=list)
    chrome_instance_path: str | None = None
    wss_url: str | None = None
    cdp_url: str | None = None
    browser_type: str = 'chromium'  # Options: 'chromium', 'firefox', 'webkit', 'msedge'
    user_data_dir: str | None = None
    use_existing_browser: bool = False

    proxy: ProxySettings | None = field(default=None)
    new_context_config: BrowserContextConfig = field(default_factory=BrowserContextConfig)

    _force_keep_browser_alive: bool = False


# @singleton: TODO - think about id singleton makes sense here
# @dev By default this is a singleton, but you can create multiple instances if you need to.
class Browser:
    """
    Playwright browser on steroids.

    This is persistant browser factory that can spawn multiple browser contexts.
    It is recommended to use only one instance of Browser per your application (RAM usage will grow otherwise).
    """

    def __init__(
        self,
        config: BrowserConfig = BrowserConfig(),
    ):
        logger.debug('Initializing new browser')
        self.config = config
        self.playwright: Playwright | None = None
        self.playwright_browser: PlaywrightBrowser | None = None
        self.browser_context = None
        self.temp_dir = None

        self.disable_security_args = []
        if self.config.disable_security:
            self.disable_security_args = [
                '--disable-web-security',
                '--disable-site-isolation-trials',
                '--disable-features=IsolateOrigins,site-per-process',
            ]

    async def new_context(self, config: BrowserContextConfig = BrowserContextConfig()) -> BrowserContext:
        """Create a browser context"""
        return BrowserContext(config=config, browser=self)

    async def get_playwright_browser(self) -> PlaywrightBrowser:
        """Get a browser context"""
        if self.playwright_browser is None:
            return await self._init()

        return self.playwright_browser

    @time_execution_async('--init (browser)')
    async def _init(self):
        """Initialize the browser session"""
        playwright = await async_playwright().start()
        browser = await self._setup_browser(playwright)

        self.playwright = playwright
        self.playwright_browser = browser

        return self.playwright_browser

    async def _setup_cdp(self, playwright: Playwright) -> PlaywrightBrowser:
        """Sets up and returns a Playwright Browser instance with anti-detection measures."""
        if not self.config.cdp_url:
            raise ValueError('CDP URL is required')
        logger.info(f'Connecting to remote browser via CDP {self.config.cdp_url}')
        browser = await playwright.chromium.connect_over_cdp(self.config.cdp_url)
        return browser

    async def _setup_wss(self, playwright: Playwright) -> PlaywrightBrowser:
        """Sets up and returns a Playwright Browser instance with anti-detection measures."""
        if not self.config.wss_url:
            raise ValueError('WSS URL is required')
        logger.info(f'Connecting to remote browser via WSS {self.config.wss_url}')
        browser = await playwright.chromium.connect(self.config.wss_url)
        return browser

    async def _setup_browser_with_instance(self, playwright: Playwright) -> PlaywrightBrowser:
        """Sets up and returns a Playwright Browser instance with anti-detection measures."""
        if not self.config.chrome_instance_path:
            raise ValueError('Chrome instance path is required')
        import subprocess

        import requests

        try:
            # Check if browser is already running
            response = requests.get('http://localhost:9222/json/version', timeout=2)
            if response.status_code == 200:
                logger.info('Reusing existing Chrome instance')
                browser = await playwright.chromium.connect_over_cdp(
                    endpoint_url='http://localhost:9222',
                    timeout=20000,  # 20 second timeout for connection
                )
                return browser
        except requests.ConnectionError:
            logger.debug('No existing Chrome instance found, starting a new one')

        # Start a new Chrome instance
        subprocess.Popen(
            [
                self.config.chrome_instance_path,
                '--remote-debugging-port=9222',
            ]
            + self.config.extra_chromium_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Attempt to connect again after starting a new instance
        for _ in range(10):
            try:
                response = requests.get('http://localhost:9222/json/version', timeout=2)
                if response.status_code == 200:
                    break
            except requests.ConnectionError:
                pass
            await asyncio.sleep(1)

        # Attempt to connect again after starting a new instance
        try:
            browser = await playwright.chromium.connect_over_cdp(
                endpoint_url='http://localhost:9222',
                timeout=20000,  # 20 second timeout for connection
            )
            return browser
        except Exception as e:
            logger.error(f'Failed to start a new Chrome instance.: {str(e)}')
            raise RuntimeError(
                ' To start chrome in Debug mode, you need to close all existing Chrome instances and try again otherwise we can not connect to the instance.'
            )

    async def _connect_to_existing_edge(self, playwright: Playwright) -> PlaywrightBrowser:
        """Connect to an existing Edge instance"""
        import subprocess
        import time
        import requests
        
        # Try to find a running edge instance first
        try:
            response = requests.get('http://localhost:9222/json/version', timeout=2)
            if response.status_code == 200:
                logger.info('Found existing Edge instance, connecting to it')
                browser = await playwright.chromium.connect_over_cdp(
                    endpoint_url='http://localhost:9222',
                    timeout=20000,
                )
                return browser
        except requests.ConnectionError:
            # If no running instance, we'll start one
            pass
            
        # Get the Edge executable path
        edge_path = self._get_edge_path()
        
        # Launch Edge with remote debugging enabled
        logger.info('Starting Edge with remote debugging enabled')
        cmd = [
            edge_path,
            '--remote-debugging-port=9222',
            '--user-data-dir=' + self.config.user_data_dir,
            '--no-first-run',
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        # Wait for the browser to start
        max_wait = 30  # 30 seconds max
        for _ in range(max_wait):
            try:
                response = requests.get('http://localhost:9222/json/version', timeout=2)
                if response.status_code == 200:
                    logger.info('Edge started successfully')
                    break
            except requests.ConnectionError:
                time.sleep(1)
        else:
            raise TimeoutError("Failed to start Edge browser in time")
        
        # Connect to the browser
        browser = await playwright.chromium.connect_over_cdp(
            endpoint_url='http://localhost:9222',
            timeout=20000,
        )
        
        return browser

    async def _setup_standard_browser(self, playwright: Playwright) -> PlaywrightBrowser:
        """Sets up and returns a Playwright Browser instance with anti-detection measures."""
        launch_args = [
            '--no-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--disable-background-timer-throttling',
            '--disable-popup-blocking',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-window-activation',
            '--disable-focus-on-load',
            '--no-first-run',
            '--no-default-browser-check',
            '--no-startup-window',
            '--window-position=0,0',
        ]
        
        # Determine which browser to launch based on browser_type
        if self.config.browser_type == 'msedge':
            # If we're supposed to use an existing browser, try to connect to it
            if self.config.use_existing_browser and self.config.user_data_dir:
                return await self._connect_to_existing_edge(playwright)
                
            # Find the Microsoft Edge executable path
            edge_path = self._get_edge_path()
            
            # If user_data_dir is provided, use it without disabling security
            if self.config.user_data_dir:
                logger.info(f'Launching Microsoft Edge with user data directory: {self.config.user_data_dir}')
                
                # Create a temporary profile based on the existing profile
                # This allows us to use disable_security while still using cookies from the existing profile
                self.temp_dir = tempfile.TemporaryDirectory(prefix="edge_profile_")
                temp_user_data_dir = self.temp_dir.name
                
                # Copy cookies and site data from the original profile
                self._copy_cookies_from_profile(self.config.user_data_dir, temp_user_data_dir)
                
                logger.info(f'Created temporary profile at: {temp_user_data_dir}')
                
                browser = await playwright.chromium.launch(
                    headless=self.config.headless,
                    executable_path=edge_path,
                    args=launch_args + self.config.extra_chromium_args + [
                        '--no-private-window',  # Disable private browsing
                        '--no-incognito',      # Alternative way to disable private browsing
                    ],
                    proxy=self.config.proxy,
                )
                
                # After browser is launched, we will create a context with the cookies we need
                context = await browser.new_context(
                    storage_state=self._get_storage_state_path(temp_user_data_dir)
                )
                
                self.browser_context = context
                return browser
            else:
                # No user_data_dir provided - use a temporary one and enable security options
                temp_dir = tempfile.TemporaryDirectory(prefix="edge_profile_")
                launch_args += self.disable_security_args
                
                browser = await playwright.chromium.launch(
                    headless=self.config.headless,
                    executable_path=edge_path,
                    args=launch_args + self.config.extra_chromium_args + [
                        f'--user-data-dir={temp_dir.name}',
                    ],
                    proxy=self.config.proxy,
                )
                
                # Store the temp dir to clean up later
                self.temp_dir = temp_dir
                return browser
        else:
            # Default to chromium for other browser types
            browser_launcher = getattr(playwright, self.config.browser_type, playwright.chromium)
            browser = await browser_launcher.launch(
                headless=self.config.headless,
                args=launch_args + self.disable_security_args + self.config.extra_chromium_args,
                proxy=self.config.proxy,
            )
            
        return browser
    
    def _copy_cookies_from_profile(self, source_profile, target_profile):
        """Copy cookies from source profile to target profile"""
        import shutil
        import os
        
        # Ensure target directory exists
        os.makedirs(target_profile, exist_ok=True)
        
        # Look for cookies file in source profile
        cookies_files = [
            os.path.join(source_profile, 'Default', 'Cookies'),
            os.path.join(source_profile, 'Default', 'Network', 'Cookies'),
            os.path.join(source_profile, 'Cookies')
        ]
        
        # Copy relevant files
        for file_path in cookies_files:
            if os.path.exists(file_path):
                target_dir = os.path.join(target_profile, os.path.dirname(file_path.replace(source_profile, '')).lstrip(os.sep))
                os.makedirs(target_dir, exist_ok=True)
                try:
                    shutil.copy2(file_path, os.path.join(target_dir, os.path.basename(file_path)))
                    logger.info(f'Copied cookies from {file_path}')
                except Exception as e:
                    logger.warning(f'Failed to copy cookies: {e}')
                    
        # Try to locate and copy the Local Storage
        local_storage_paths = [
            os.path.join(source_profile, 'Default', 'Local Storage'),
            os.path.join(source_profile, 'Local Storage')
        ]
        
        for ls_path in local_storage_paths:
            if os.path.exists(ls_path) and os.path.isdir(ls_path):
                target_ls_dir = os.path.join(target_profile, ls_path.replace(source_profile, '').lstrip(os.sep))
                try:
                    os.makedirs(os.path.dirname(target_ls_dir), exist_ok=True)
                    shutil.copytree(ls_path, target_ls_dir, dirs_exist_ok=True)
                    logger.info(f'Copied local storage from {ls_path}')
                except Exception as e:
                    logger.warning(f'Failed to copy local storage: {e}')
    
    def _get_storage_state_path(self, profile_dir):
        """Get the path to the storage state file"""
        import glob
        import os
        
        # Look for storage state files
        cookies_files = glob.glob(os.path.join(profile_dir, '**', 'Cookies'), recursive=True)
        
        if cookies_files:
            return os.path.dirname(cookies_files[0])
        return None
    
    def _get_edge_path(self) -> str:
        """Returns the path to Microsoft Edge executable based on the operating system."""
        import platform
        system = platform.system()
        
        if system == 'Windows':
            # Common Edge paths on Windows
            possible_paths = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    return path
            raise FileNotFoundError("Microsoft Edge executable not found. Please provide the path explicitly.")
            
        elif system == 'Darwin':  # macOS
            return "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
            
        elif system == 'Linux':
            # Check common Linux locations
            possible_paths = [
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
                "/opt/microsoft/msedge/msedge"
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    return path
            raise FileNotFoundError("Microsoft Edge executable not found. Please provide the path explicitly.")
            
        else:
            raise OSError(f"Unsupported operating system: {system}")

    def _get_default_edge_user_data_dir(self) -> str:
        """Returns the default user data directory for Microsoft Edge based on the operating system."""
        import platform
        system = platform.system()
        home = Path.home()
        
        if system == 'Windows':
            return str(home / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data")
        elif system == 'Darwin':  # macOS
            return str(home / "Library" / "Application Support" / "Microsoft Edge")
        elif system == 'Linux':
            return str(home / ".config" / "microsoft-edge")
        else:
            raise OSError(f"Unsupported operating system: {system}")

    async def _setup_browser(self, playwright: Playwright) -> PlaywrightBrowser:
        """Sets up and returns a Playwright Browser instance with anti-detection measures."""
        try:
            if self.config.cdp_url:
                return await self._setup_cdp(playwright)
            if self.config.wss_url:
                return await self._setup_wss(playwright)
            elif self.config.chrome_instance_path:
                return await self._setup_browser_with_instance(playwright)
            else:
                return await self._setup_standard_browser(playwright)
        except Exception as e:
            logger.error(f'Failed to initialize Playwright browser: {str(e)}')
            raise

    async def close(self):
        """Close the browser instance"""
        try:
            if not self.config._force_keep_browser_alive:
                # First close the browser context if it exists
                if self.browser_context:
                    await self.browser_context.close()
                    self.browser_context = None
                
                # Then close browser if it exists
                if self.playwright_browser:
                    await self.playwright_browser.close()
                    del self.playwright_browser
                
                # Finally stop playwright
                if self.playwright:
                    await self.playwright.stop()
                    del self.playwright
                
                # Clean up temporary directory if it exists
                if self.temp_dir:
                    try:
                        self.temp_dir.cleanup()
                    except Exception as e:
                        logger.debug(f'Failed to clean up temporary directory: {e}')
                    self.temp_dir = None

        except Exception as e:
            logger.debug(f'Failed to close browser properly: {e}')
        finally:
            self.browser_context = None
            self.playwright_browser = None
            self.playwright = None
            self.temp_dir = None

            gc.collect()

    def __del__(self):
        """Async cleanup when object is destroyed"""
        try:
            if self.playwright_browser or self.playwright or self.browser_context or self.temp_dir:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self.close())
                else:
                    asyncio.run(self.close())
        except Exception as e:
            logger.debug(f'Failed to cleanup browser in destructor: {e}')
