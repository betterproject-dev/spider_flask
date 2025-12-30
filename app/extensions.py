import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from keras.models import load_model
from flask_socketio import SocketIO
import joblib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(BASE_DIR, 'sensor_lstm_model_v2.keras')
scaler_x_path = os.path.join(BASE_DIR, 'scaler_X.pkl')
scaler_y_path = os.path.join(BASE_DIR, 'scaler_y.pkl')
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
model = load_model(model_path)
scaler_X = joblib.load(scaler_x_path)
scaler_y = joblib.load(scaler_y_path)