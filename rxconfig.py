import reflex as rx
from reflex.plugins.tailwind_v3 import TailwindV3Plugin


config = rx.Config(
    app_name="gastroflow",
    app_module_import="gastroflow.app",
    frontend_port=3000,
    backend_port=8000,
    backend_host="127.0.0.1",
    api_url="http://127.0.0.1:8000",
    plugins=[
        TailwindV3Plugin(
            config={
                "theme": {
                    "extend": {
                        "colors": {
                            "gastro": {
                                "gold": "#D19C40",
                                "cream": "#F0E9CF",
                                "red": "#A90F2B",
                                "green": "#172e1d",
                            }
                        },
                        "fontFamily": {
                            "gastro": ["Cooper BT", "Georgia", "serif"],
                            "script": ["Playlist Script", "TAN St. Canard", "Georgia", "serif"],
                        },
                    }
                }
            }
        )
    ],
)
