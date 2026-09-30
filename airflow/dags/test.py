from datetime import datetime
from airflow.decorators import dag, task

@dag(
    dag_id="minimal_test_dag",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["test"],
)
def minimal_test_dag():

    @task()
    def print_hello():
        print("Hello from task 1!")
        return "Task 1 completed"

    @task()
    def print_world(upstream_message: str):
        print(f"Task 2 received: {upstream_message}")
        print("World!")

    message = print_hello()
    print_world(message)

test_dag = minimal_test_dag()

if __name__ == "__main__":
    print("Running local DAG test execution...")
    test_dag.test()
