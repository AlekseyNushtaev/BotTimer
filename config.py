from dotenv import load_dotenv
import os

load_dotenv()

TG_TOKEN = os.environ.get("TG_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
DELTA = int(os.environ.get("DELTA"))
