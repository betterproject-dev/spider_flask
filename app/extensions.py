from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from keras.models import load_model
import joblib

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
model = load_model('./sensor_lstm_model_v2.keras')
scaler_X = joblib.load('./scaler_X.pkl')
scaler_y = joblib.load('./scaler_y.pkl')