# Cohere
# export MODEL_NAME="openai/c3-111b-rag-sft-2aazwluv-fp8-vllm"
# MODEL_NAME = "openai/c3-111b-code-sft-xxs9o2iz-fp16-vllm"
# MODEL_NAME = "openai/c3-sweep-l832wml9-hmt2-fp16"
# MODEL_NAME = "openai/c3-sweep-gxlbwnw2-ebak-fp16"
# MODEL_NAME = "openai/c3-sweep-dwb071sm-zhat-fp16"
#export MODEL_NAME="openai/c3-111b-code-sft-2iib0oqr-fp16-vllm"
export MODEL_NAME="openai/c3-111b-code-sft-souwe4re-fp16-vllm"
export OPENAI_API_BASE="https://stg.api.cohere.ai/compatibility/v1"
export OPENAI_API_KEY=$CO_API_KEY_STAGING
export CONCURRENT=4
export MAX_OUTPUT_TOKENS=8000

# Qwen
#export OPENAI_API_BASE="https://api.together.xyz/v1"
#export OPENAI_API_KEY=$TOGETHER_API_KEY
#export MODEL_NAME="openai/Qwen/Qwen3-235B-A22B-fp8-tput"
#export MAX_OUTPUT_TOKENS=32000
#export MAX_OUTPUT_TOKENS=16000
#export CONCURRENT=32

# Claude
#export OPENAI_API_KEY=$ANTHROPIC_API_KEY
#export MODEL_NAME="claude-sonnet-4-20250514"
#export MAX_OUTPUT_TOKENS=8000
#export CONCURRENT=16

# DS
#export OPENAI_API_BASE="https://api.together.xyz/v1"
#export OPENAI_API_KEY=$TOGETHER_API_KEY
#export MODEL_NAME="openai/deepseek-ai/DeepSeek-V3"

#export OPENAI_API_KEY=$DEEPSEEK_API_KEY
#export MODEL_NAME="deepseek/deepseek-chat"
#

# Cohere prod
#export MODEL_NAME="command-a-03-2025"
#export OPENAI_API_KEY=$CO_API_KEY



#export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default.yaml
#export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default_backticks.yaml
#export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default_thought_action.yaml
#export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default_xml.yaml
#export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default_lastn.yaml
#export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default_last10swesmith.yaml
export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default_last10.yaml
#export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default_thoughtaction_lastn.yaml
#export CONFIG=/home/justinchiu_cohere_com/SWE-agent/config/default_lastn_oh.yaml

uv run rl_sweagent/run_public_benchmark.py \
    --scenario-id scn_306hjRxQOkg4BNxdgIeQM \
    --config-path $CONFIG \
    --timeout-secs 1200 \
    --concurrent_runs $CONCURRENT \
    --openai-api-base $OPENAI_API_BASE \
    --openai-api-key $OPENAI_API_KEY \
    --model-name $MODEL_NAME \
    --max_output_tokens $MAX_OUTPUT_TOKENS #--keep-devbox

echo $CONFIG
echo $MODEL_NAME
