from setuptools import find_packages, setup

package_name = 'scout_perception'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Alvaro',
    maintainer_email='alvcm1501@gmail.com',
    description='Scout perception nodes: plant detector, species ID, pin localizer, bubble panorama.',
    license='MIT',
    entry_points={
        'console_scripts': [
            'detector_node = scout_perception.detector_node:main',
            'panorama_node = scout_perception.panorama_node:main',
            'species_node = scout_perception.species_node:main',
            'localizer_node = scout_perception.localizer_node:main',
            'whisper_node = scout_perception.whisper_node:main',
        ],
    },
)
