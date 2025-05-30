# Cohere
MODEL_NAME = "openai/c3-111b-rag-sft-2aazwluv-fp8-vllm"
# MODEL_NAME = "openai/c3-111b-code-sft-xxs9o2iz-fp16-vllm"
# MODEL_NAME = "openai/c3-sweep-l832wml9-hmt2-fp16"
# MODEL_NAME = "openai/c3-sweep-gxlbwnw2-ebak-fp16"
# MODEL_NAME = "openai/c3-sweep-dwb071sm-zhat-fp16"
OPENAI_API_BASE="https://stg.api.cohere.ai/compatibility/v1"
OPENAI_API_KEY=$CO_API_KEY_STAGING

# Qwen
OPENAI_API_BASE="https://api.together.xyz/v1"
OPENAI_API_KEY=$TOGETHER_API_KEY
MODEL_NAME = "openai/Qwen/Qwen3-235B-A22B-fp8-tput"


uv run run_public_benchmark.py \
    --scenario-id scn_2zmp1tPUbIyDflEK7QYUz \
    --config-path /home/justinchiu_cohere_com/SWE-agent/config/sweagent_0_7/07_thought_action.yaml \
    --timeout-secs 900 \
    --openai-api-base $OPENAI_API_BASE \
    --openai-api-key $OPENAI_API_KEY \
    --model-name $MODEL_NAME

