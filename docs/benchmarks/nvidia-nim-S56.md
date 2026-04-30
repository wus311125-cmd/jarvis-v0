| Model | HK | Chat (A) | FC Single (B) | FC Multi (C) | Avg Latency | Recommendation |
|---|---:|---|---|---|---:|---|
| nvidia/nemotron-3-nano-30b-a3b | Yes | — | OK | No | 1.28s | OK for FC |
| nvidia/nemotron-3-super-120b-a12b | Yes | Function calling 是指在程式執行時，根據特定條件或需求自動調用預先定義好的函式（function）來執行特定任務的機制。 | OK | Ask | 13.05s | OK for FC |
| deepseek-ai/deepseek-v4-flash | Yes | Function calling 係指讓 AI 模型能夠根據用戶指令，自動選擇並呼叫預先定義好的外部函數或 API 來執行特定任務（例如查天氣、發郵件），從而獲 | OK | Ask | 10.20s | OK for FC |
| qwen/qwen3.5-122b-a10b | Yes | Function calling 係一種讓大型語言模型（LLM）能夠識別用戶意圖，並自動生成結構化數據以調用外部程式函數（例如查詢天氣、執行計算或操作資料庫）， | OK | Ask | 2.49s | OK for FC |
| nvidia/llama-3.1-nemotron-nano-8b-v1 | Yes | 一個簡潔的句子："function calling 是指在程式碼中呼叫一個定義好的 function，讓它執行其內容。" | OK | OK | 3.18s | OK for FC |
| nvidia/llama-3.3-nemotron-super-49b-v1 | Yes | Function calling 是指在程式執行過程中，呼叫（invoke）並執行事先定義好的程式碼塊（function或方法），以完成特定任務的動作。 | OK | OK | 2.72s | Use Nemotron Super 49B as best; Nano 8B as lightweight fallback |

**Skipped / Errored models**


| Model | Reason |
|---|---|
| z-ai/glm-5.1 | Timeout |
| nvidia/gpt-oss-120b | 404 Not Found |
| nvidia/gpt-oss-20b | 404 Not Found |
| google/gemma-4-31b-it | Timeout |
| moonshot/kimi-2.5 | 404 Not Found |


最佳推薦：Nemotron Super 49B，輕量 fallback：Nemotron Nano 8B。