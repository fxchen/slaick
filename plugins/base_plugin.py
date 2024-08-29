import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from slack_bolt import BoltContext


class BasePlugin(ABC):
    @abstractmethod
    def process_message(
        self, context: BoltContext, message: Dict[str, Any], logger: logging.Logger
    ) -> List[Dict[str, Any]]:
        pass

    @property
    def run_on_last_message_only(self) -> bool:
        return False


class PluginManager:
    def __init__(self):
        self.plugins = []

    def register_plugin(self, plugin: BasePlugin):
        self.plugins.append(plugin)

    def process_message(
        self,
        context: BoltContext,
        message: Dict[str, Any],
        logger: logging.Logger,
        is_last_message: bool,
    ) -> List[Dict[str, Any]]:
        content = []
        for plugin in self.plugins:
            if plugin.run_on_last_message_only and not is_last_message:
                continue
            content.extend(plugin.process_message(context, message, logger))
        return content
