"""PaperDesk: a local PDF paper reader with pluggable AI assistants.

APP_NAME is the display name. Persistent identifiers must never follow a branding change.
"""

__version__ = "0.4.2"
APP_NAME = "PaperDesk"
APP_ID = "paperdesk"
MAC_BUNDLE_ID = "org.paperdesk.Paperdesk"
SOURCE_APP_ID = MAC_BUNDLE_ID + ".source"  # source installs: the macOS app's bundle ID, the Windows taskbar ID
MAC_MINIMUM_VERSION = "15.0"
DATA_DIR_NAME = "Paperdesk"
STORAGE_ID = "paperdesk"
KEYCHAIN_SERVICE = "paperdesk"
