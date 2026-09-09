from glob import glob
from setuptools import setup

package_name = "gazebo_factory_twin"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/worlds", glob("worlds/*.sdf"))
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={
    "console_scripts": [
        "factory_twin_node = gazebo_factory_twin.factory_twin_node:main",
        "telemetry_logger = gazebo_factory_twin.telemetry_logger:main",
        "production_logger = gazebo_factory_twin.production_logger:main"
    ]
},
)
