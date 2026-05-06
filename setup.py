# -*- coding: utf-8 -*-
import sys
from setuptools import setup, find_packages

# ==================== IDE 运行兼容逻辑 ====================
# 如果直接在 PyCharm 里点运行（没有传参数），
# 我们手动给它加上 'bdist_wheel' 参数，让它执行打包动作
if len(sys.argv) <= 1:
    sys.argv.append('bdist_wheel')
    # 如果你还想顺便清理一下之前的旧文件，可以取消下面这一行的注释
    # sys.argv.append('--clean')
# ========================================================

setup(
    name="hik_industrial_sdk",
    version="4.6.0.1",
    author="LCL",
    description="海康工业相机SDK绿化版，支持MvImport无感替换",

    # 指定源码结构
    package_dir={"": "src"},
    packages=find_packages(where="src"),

    # 包含 bin 目录下的所有 DLL 和文件夹
    # 这里的 "MvImport" 必须对应你 src 下的文件夹名
    package_data={
        "MvImport": ["bin/**/*", "bin/*"],
    },
    include_package_data=True,

    install_requires=[
        "numpy",
        "opencv-python",
    ],
    zip_safe=False,  # 因为含有 DLL，建议设置为 False
)