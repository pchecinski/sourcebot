'''
Sourcebot configuration
'''
# Third-party libraries
import yaml

MAIN_CONFIG = "config/main.yml"
ROLES_SETTINGS = "config/roles.yml"

# Load config files
with open(MAIN_CONFIG) as file:
    config = yaml.safe_load(file)
with open(ROLES_SETTINGS) as file:
    roles_settings = yaml.safe_load(file)
