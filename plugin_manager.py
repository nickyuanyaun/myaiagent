import os
import sys
import importlib
import importlib.util
import logging

logger = logging.getLogger(__name__)

class PluginManager:
    def __init__(self, plugins_dir="plugins"):
        self.plugins_dir = plugins_dir
        self.plugins = {}  # Format: { "plugin_name": module_object }
        self.metadata = [] # Format: [ {"name": "...", "description": "...", "args": {...}} ]
        
        # Ensure directory exists and is a package
        if not os.path.exists(self.plugins_dir):
            os.makedirs(self.plugins_dir)
        
        init_file = os.path.join(self.plugins_dir, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write("# Plugin Package\n")
                
        # Add to sys.path if not there so absolute imports work
        if os.path.abspath(self.plugins_dir) not in sys.path:
            sys.path.insert(0, os.path.abspath("."))

        self.reload_plugins()

    def reload_plugins(self):
        """Scans the plugins directory and loads/reloads all .py files."""
        self.plugins.clear()
        self.metadata.clear()
        
        for filename in os.listdir(self.plugins_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                plugin_name = filename[:-3]
                try:
                    # Dynamically import or reload the module
                    module_name = f"{self.plugins_dir}.{plugin_name}"
                    
                    if module_name in sys.modules:
                        module = importlib.reload(sys.modules[module_name])
                    else:
                        module = importlib.import_module(module_name)
                    
                    # Verify validity (Must have PLUGIN_METADATA and an execute function)
                    if hasattr(module, "PLUGIN_METADATA") and hasattr(module, "execute"):
                        self.plugins[plugin_name] = module
                        meta = module.PLUGIN_METADATA
                        meta["name"] = plugin_name # Ensure programmatic name matches filename
                        self.metadata.append(meta)
                        logger.info(f"Successfully loaded plugin: {plugin_name}")
                    else:
                        logger.warning(f"Plugin {plugin_name} missing PLUGIN_METADATA or execute() function. Ignored.")
                        
                except Exception as e:
                    logger.error(f"Failed to load plugin {plugin_name}: {e}")

    def get_plugin_descriptions(self) -> str:
        """Returns a formatted string of all available plugins for the AI's System Prompt."""
        if not self.metadata:
            return "No custom plugins currently loaded."
            
        desc = "AVAILABLE CUSTOM PLUGINS:\n"
        for meta in self.metadata:
            desc += f"- Name: {meta['name']}\n"
            desc += f"  Description: {meta.get('description', 'No description')}\n"
            desc += f"  Arguments Needed: {meta.get('args', 'None')}\n\n"
        return desc

    def execute_plugin(self, plugin_name: str, **kwargs):
        """Executes a loaded plugin with the given arguments."""
        if plugin_name not in self.plugins:
            return f"Error: Plugin '{plugin_name}' not found."
            
        try:
            module = self.plugins[plugin_name]
            result = module.execute(**kwargs)
            return result
        except Exception as e:
            logger.error(f"Error executing plugin {plugin_name}: {e}")
            return f"Plugin Execution Error: {e}"

    def write_plugin(self, plugin_name: str, code: str) -> bool:
        """Writes new plugin code to disk and reloads."""
        # Safety normalization
        plugin_name = "".join(c for c in plugin_name if c.isalnum() or c == '_')
        filepath = os.path.join(self.plugins_dir, f"{plugin_name}.py")
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            
            logger.info(f"Wrote new plugin code to {filepath}")
            self.reload_plugins()
            return True
        except Exception as e:
            logger.error(f"Failed to write plugin {plugin_name}: {e}")
            return False
