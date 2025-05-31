# Cohere
export MODEL_NAME="openai/c3-111b-rag-sft-2aazwluv-fp8-vllm"
# MODEL_NAME = "openai/c3-111b-code-sft-xxs9o2iz-fp16-vllm"
# MODEL_NAME = "openai/c3-sweep-l832wml9-hmt2-fp16"
# MODEL_NAME = "openai/c3-sweep-gxlbwnw2-ebak-fp16"
# MODEL_NAME = "openai/c3-sweep-dwb071sm-zhat-fp16"
export OPENAI_API_BASE="https://stg.api.cohere.ai/compatibility/v1"
export OPENAI_API_KEY=$CO_API_KEY_STAGING

# Qwen
export OPENAI_API_BASE="https://api.together.xyz/v1"
export OPENAI_API_KEY=$TOGETHER_API_KEY
export MODEL_NAME="openai/Qwen/Qwen3-235B-A22B-fp8-tput"

# Claude
export OPENAI_API_KEY=$ANTHROPIC_API_KEY
export MODEL_NAME="claude-sonnet-4-20250514"
#export MODEL_NAME="claude-opus-4-20250514"

uv run run_public_benchmark.py \
    --benchmark-id bmd_2zmp3Mu3LhWu7yDVIfq3m \
    --config-path /home/justinchiu_cohere_com/SWE-agent/config/default.yaml \
    --timeout-secs 900 \
    --openai-api-base $OPENAI_API_BASE \
    --openai-api-key $OPENAI_API_KEY \
    --model-name $MODEL_NAME

