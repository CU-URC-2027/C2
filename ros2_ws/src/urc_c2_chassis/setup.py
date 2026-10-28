from setuptools import find_packages, setup

setup(name='urc_c2_chassis', version='0.1.0', packages=find_packages(),
      data_files=[('share/ament_index/resource_index/packages', ['resource/urc_c2_chassis']),
                  ('share/urc_c2_chassis', ['package.xml'])],
      install_requires=['setuptools'], zip_safe=False,
      maintainer='CU URC C2 team', maintainer_email='maintainers@example.invalid',
      description='ROS 2 chassis command/feedback bench prototype',
      license='LicenseRef-Proprietary',
      entry_points={'console_scripts': [
          'c2_operator = urc_c2_chassis.dashboard:main',
          'chassis_bridge = urc_c2_chassis.bridge_node:main',
          'smoke_test = urc_c2_chassis.smoke_test:main']})
