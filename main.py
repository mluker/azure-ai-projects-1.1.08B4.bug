import os
import logging
import shutil
import time
from pathlib import Path
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import EvaluatorConfiguration, Evaluation, EvaluatorIds, InputDataset
from azure.ai.evaluation import RougeType

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
DATASET_NAME_BASE = "evaluation_dataset"
DATASET_VERSION = "1.0"
HOW_MANY_RUNS = 5

endpoint = os.environ["PROJECT_ENDPOINT"]
model_endpoint = os.environ["MODEL_ENDPOINT"]
model_deployment_name = os.environ["MODEL_DEPLOYMENT_NAME"]


def create_dataset_file_from_template(target_path: str, template_path: str) -> bool:
    """Create a dataset file from template."""
    try:
        if not Path(template_path).exists():
            logger.error(f"Template file not found: {template_path}")
            return False

        # Create data directory if it doesn't exist
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)

        # Copy template to target location
        shutil.copy2(template_path, target_path)
        logger.info(f"Created dataset file: {target_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create dataset file {target_path}: {e}")
        return False


def create_evaluators(model_deployment_name: str, endpoint: str) -> dict:
    """Create evaluator configurations."""
    return {
        "relevance": EvaluatorConfiguration(
            id=EvaluatorIds.RELEVANCE.value,
            init_params={"deployment_name": model_deployment_name},
            data_mapping={
                "query": "${data.query}",
                "response": "${data.response}",
                "context": "${data.context}",
            },
        ),
        "violence": EvaluatorConfiguration(
            id=EvaluatorIds.VIOLENCE.value,
            init_params={"azure_ai_project": endpoint},
            data_mapping={"query": "${data.query}", "response": "${data.response}"},
        ),
        "f1_score": EvaluatorConfiguration(
            id=EvaluatorIds.F1_SCORE.value,
            data_mapping={
                "response": "${data.response}",
                "ground_truth": "${data.ground_truth}",
            },
        ),
        "rouge": EvaluatorConfiguration(
            id=EvaluatorIds.ROUGE_SCORE.value,
            init_params={"rouge_type": RougeType.ROUGE_L},
            data_mapping={
                "response": "${data.response}",
                "ground_truth": "${data.ground_truth}",
            },
        ),
    }


def main():

    project_client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    evaluators = create_evaluators(model_deployment_name, endpoint)
    existing_datasets = project_client.datasets.list()
    dataset_lookup = {(dataset.name, dataset.version): dataset.id for dataset in existing_datasets}

    for i in range(1, HOW_MANY_RUNS + 1):
        data_set_name = f"{DATASET_NAME_BASE}_{i}"
        file_path = f"./data/{data_set_name}.jsonl"

        if not Path(file_path).exists():
            template_file = f"./data/{DATASET_NAME_BASE}.jsonl"
            create_dataset_file_from_template(file_path, template_file)

        dataset_key = (data_set_name, DATASET_VERSION)
        if dataset_key in dataset_lookup:
            data_id = dataset_lookup[dataset_key]
        else:
            dataset = project_client.datasets.upload_file(
                name=data_set_name,
                version=DATASET_VERSION,
                file_path=file_path,
            )
            data_id = dataset.id
            dataset_lookup[dataset_key] = data_id

        evaluation_name = f"Evaluation_{i}_{data_set_name}"
        evaluation_description = f"Evaluation run {i} using {', '.join(evaluators.keys())} evaluators"

        evaluation = Evaluation(
            display_name=evaluation_name,
            description=evaluation_description,
            data=InputDataset(id=data_id),
            evaluators=evaluators,
        )

        try:
            evaluation_response = project_client.evaluations.create(evaluation)
            logger.info(f"Created evaluation: {evaluation_response.name} (Status: {evaluation_response.status})")
        except Exception as e:
            logger.error(f"Failed to create evaluation {evaluation_name}: {e}")
            continue

    logger.info("Evaluation processing completed!")

if __name__ == "__main__":
    main()
