# NVIDIA NIM Benchmark (S56)

Base: https://integrate.api.nvidia.com/v1

## nvidia/nemotron-3-nano-30b-a3b
- Scenario A: statuses=['200'], latencies_ms=[1308]
- Scenario B: statuses=['200', '200', '200'], latencies_ms=[914, 923, 982]
- Scenario C: statuses=['200', '200', '200'], latencies_ms=[1837, 1170, 1816]

## nvidia/nemotron-3-super-120b-a12b
- Scenario A: statuses=['200'], latencies_ms=[11620]
- Scenario B: statuses=['200', '200', '200'], latencies_ms=[3394, 19110, 1987]
- Scenario C: statuses=['200', '200', '200'], latencies_ms=[4996, 41199, 9010]

## deepseek-ai/deepseek-v4-flash
- Scenario A: statuses=['200'], latencies_ms=[5618]
- Scenario B: statuses=['200', '200', '200'], latencies_ms=[3156, 6309, 12360]
- Scenario C: statuses=['200', '200', '200'], latencies_ms=[4036, 36807, 3093]

## z-ai/glm-5.1
- Scenario A: statuses=['ERR'], latencies_ms=[60008]

## qwen/qwen3.5-122b-a10b
- Scenario A: statuses=['200'], latencies_ms=[890]
- Scenario B: statuses=['200', '200', '200'], latencies_ms=[6350, 1088, 1576]
- Scenario C: statuses=['200', '200', '200'], latencies_ms=[3915, 1013, 2574]

## nvidia/gpt-oss-120b
- Scenario A: statuses=['404'], latencies_ms=[248]

## nvidia/gpt-oss-20b
- Scenario A: statuses=['404'], latencies_ms=[261]

## nvidia/llama-3.1-nemotron-nano-8b-v1
- Scenario A: statuses=['200'], latencies_ms=[1698]
- Scenario B: statuses=['200', '200', '200'], latencies_ms=[2766, 4552, 3128]
- Scenario C: statuses=['200', '200', '200'], latencies_ms=[2975, 2157, 4994]

## nvidia/llama-3.3-nemotron-super-49b-v1
- Scenario A: statuses=['200'], latencies_ms=[1819]
- Scenario B: statuses=['200', '200', '200'], latencies_ms=[1360, 1191, 7804]
- Scenario C: statuses=['200', '200', '200'], latencies_ms=[1940, 3270, 1655]

## google/gemma-4-31b-it
- Scenario A: statuses=['ERR'], latencies_ms=[60006]

## moonshot/kimi-2.5
- Scenario A: statuses=['404'], latencies_ms=[300]
