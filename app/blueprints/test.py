# 테스트용(추후 삭제)

from flask import Blueprint
from app.models.machines import Machines
from app.models.sensors import Sensors

bp = Blueprint('test', __name__)
