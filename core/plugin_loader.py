import os
import sys
import importlib.util
import asyncio
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class PluginHandler(FileSystemEventHandler):
    def __init__(self, tool_manager, plugins_dir):
        self.tool_manager = tool_manager
        self.plugins_dir = Path(plugins_dir)
        self._load_all()

    def _load_all(self):
        """Carica tutti i plugin presenti all'avvio."""
        print(f"[PLUGIN] Caricamento iniziale da {self.plugins_dir}...")
        for file in self.plugins_dir.glob("*.py"):
            if file.name != "__init__.py":
                self._load_plugin(file)

    def _load_plugin(self, file_path):
        """Carica o ricarica un singolo plugin."""
        module_name = file_path.stem
        try:
            # Caricamento dinamico del modulo
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Cerca classi che terminano con 'Tool'
            found = False
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr_name.endswith("Tool") and attr_name != "Tool":
                    tool_name = module_name.replace("_tool", "")
                    self.tool_manager.register_tool(tool_name, attr())
                    found = True
            
            if found:
                print(f"[PLUGIN] Plugin '{module_name}' caricato con successo.")
            else:
                print(f"[PLUGIN] Avviso: Nessuna classe *Tool trovata in {module_name}.")
                
        except Exception as e:
            print(f"[PLUGIN] Errore caricamento {module_name}: {e}")

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            print(f"[PLUGIN] File modificato: {event.src_path}")
            self._load_plugin(Path(event.src_path))

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            print(f"[PLUGIN] Nuovo file: {event.src_path}")
            self._load_plugin(Path(event.src_path))

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            tool_name = Path(event.src_path).stem.replace("_tool", "")
            print(f"[PLUGIN] File eliminato: {event.src_path}")
            self.tool_manager.unregister_tool(tool_name)

class PluginLoader:
    def __init__(self, tool_manager, plugins_dir="plugins"):
        self.tool_manager = tool_manager
        self.plugins_dir = plugins_dir
        os.makedirs(self.plugins_dir, exist_ok=True)
        self.event_handler = PluginHandler(self.tool_manager, self.plugins_dir)
        self.observer = Observer()

    def start(self):
        """Avvia il monitoraggio della cartella plugins."""
        self.observer.schedule(self.event_handler, self.plugins_dir, recursive=False)
        self.observer.start()
        print(f"[PLUGIN] Hot-reload attivo sulla cartella '{self.plugins_dir}'.")

    def stop(self):
        self.observer.stop()
        self.observer.join()
