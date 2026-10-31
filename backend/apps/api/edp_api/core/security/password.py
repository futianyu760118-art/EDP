"""Argon2id 密码哈希与校验（argon2-cffi，默认参数即 Argon2id）。"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

# 时序垫片：模块导入时预生成一次的常量哈希——登录"用户不存在"路径执行
# 一次与真实校验等价的 argon2 验证，使响应时间与"密码错误"不可区分
# （防用户名枚举）；随机盐不影响用途，仅需校验成本相同。
_DUMMY_HASH = _hasher.hash("edp-timing-dummy-password")


def hash_password(password: str) -> str:
    """生成 Argon2id 哈希（随机盐，$argon2id$ 前缀）。"""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码与哈希是否匹配；不匹配或哈希格式非法（InvalidHash）均返回 False。"""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def timing_dummy_verify(password: str) -> None:
    """时序垫片：执行一次等价 argon2 校验并丢弃结果（用户不存在路径调用）。"""
    verify_password(password, _DUMMY_HASH)
