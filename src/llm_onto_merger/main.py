from agent_framework import AgentExecutor, WorkflowBuilder

from .load_arguments import load_arguments


async def _main():
    loaded_args = load_arguments()

    input_data = (
        f"Base Ontology:\n{loaded_args.base_content}\n\n"
        f"Candidate Ontology:\n{loaded_args.candidate_content}\n\n"
        f"Mappings:\n{loaded_args.mappings_content}"
    )

    executor_executor = AgentExecutor(executor_agent, context_mode="last_agent")
    merge_executor = AgentExecutor(merge_agent, context_mode="last_agent")

    workflow_agent = (
        WorkflowBuilder(
            start_executor=executor_executor,
            output_executors=[merge_executor],
        )
        .add_edge(executor_executor, merge_executor)
        .build()
        .as_agent()
    )

    async with workflow_agent as agent:
        response = await agent.run(input_data)
        with open(loaded_args.output_path, "w") as f:
            f.write(response.text)
        print(f"Merged ontology saved to {loaded_args.output_path}")


def main():
    import asyncio

    asyncio.run(_main())


if __name__ == "__main__":
    main()
