'''
Sourcebot configuration
'''
# Third-party libraries
import yaml

MAIN_CONFIG = "config/main.yml"
ROLES_SETTINGS = "config/roles.yml"

# Load config files
with open(MAIN_CONFIG) as main_file:
    config = yaml.safe_load(main_file)
with open(ROLES_SETTINGS) as roles_file:
    roles_settings = yaml.safe_load(roles_file)

def roles_update() -> None:
    '''
    Update roles config file with local data
    '''
    with open(ROLES_SETTINGS, 'w') as file:
        yaml.dump(roles_settings, file)
