
import logging
from api_testing_agent.config import Settings
from api_testing_agent.logging_config import setup_logging
from api_testing_agent.core.target_registry import TargetRegistry

# Main entry point for the API Testing Agent application
def main() -> None:
    setup_logging()
    
# Load settings and target registry
    settings = Settings()
    registry = TargetRegistry.from_json_file(settings.target_registry_path)

# Log the loaded settings and available targets
    logger = logging.getLogger(__name__)
    logger.info("Settings loaded.")
    logger.info("Available targets: %s", registry.list_names())

# Placeholder for additional application logic (e.g., running tests, processing targets, etc.)
if __name__ == "__main__":
    
# Call the main function to run the application    
    main()

# Initialize logging and start the application
    logger = logging.getLogger(__name__)
    logger.info("Starting API Testing Agent...")
    
    






