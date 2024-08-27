
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from slack_bolt import BoltContext
import logging


class BasePlugin(ABC):
    @abstractmethod
    def process_message(self, context: BoltContext, message: Dict[str, Any], logger: logging.Logger) -> List[Dict[str, Any]]:
        pass


class PluginManager:
    def __init__(self):
        self.plugins = []

    def register_plugin(self, plugin: BasePlugin):
        self.plugins.append(plugin)

    def process_message(self, context: BoltContext, message: Dict[str, Any], logger: logging.Logger) -> List[Dict[str, Any]]:
        content = []
        for plugin in self.plugins:
            content.extend(plugin.process_message(context, message, logger))
        return content
