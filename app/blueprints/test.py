# 테스트용(추후 삭제)

from flask import Flask, Blueprint
from app.models.machines import Machines
from app.models.sensors import Sensors
from ..extensions import socketio

app = Flask(__name__)

bp = Blueprint('test', __name__)