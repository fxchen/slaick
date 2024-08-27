import logging
import os

from slack_bolt import App

from lib.env import SLACK_APP_LOG_LEVEL
from plugins.file_plugin import FilePlugin
from slaick import Slaick

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    before_authorize=Slaick.before_authorize,
    process_before_response=True,
)

# Set up Slaick
Slaick.initialize(plugins=[FilePlugin()])
Slaick.setup_middleware(app)

# Register event handlers
Slaick.register_event_handler(app, "app_mention", Slaick.handle_app_mention)
Slaick.register_event_handler(app, "message", Slaick.handle_message)

if __name__ == "__main__":
    logging.basicConfig(level=SLACK_APP_LOG_LEVEL)
    # Start the Socket Mode handler
    Slaick.start_socket_mode(app)
