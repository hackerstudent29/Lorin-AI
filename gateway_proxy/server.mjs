import express from 'express'
import { generateText, streamText } from 'ai'

const app = express()
app.use(express.json({ limit: '2mb' }))

const PORT = process.env.GATEWAY_PROXY_PORT || 3001

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', provider: 'vercel-ai-gateway' })
})

// OpenAI-compatible chat completions endpoint
// Python backend posts to: http://localhost:3001/v1/chat/completions
app.post('/v1/chat/completions', async (req, res) => {
  const { model = 'openai/gpt-4o-mini', messages, temperature = 0.1, max_tokens = 1000, stream = false } = req.body

  if (!messages || !Array.isArray(messages)) {
    return res.status(400).json({ error: 'messages array is required' })
  }

  try {
    if (stream) {
      // Streaming: pipe SSE chunks back
      res.setHeader('Content-Type', 'text/event-stream')
      res.setHeader('Cache-Control', 'no-cache')
      res.setHeader('Connection', 'keep-alive')

      const result = streamText({ model, messages, temperature, maxTokens: max_tokens })

      let promptTokens = 0, completionTokens = 0
      for await (const chunk of result.textStream) {
        const data = {
          choices: [{ delta: { content: chunk }, finish_reason: null }]
        }
        res.write(`data: ${JSON.stringify(data)}\n\n`)
        completionTokens++
      }

      // Final usage chunk
      const usage = await result.usage
      if (usage) {
        promptTokens = usage.promptTokens || 0
        completionTokens = usage.completionTokens || 0
      }
      res.write(`data: ${JSON.stringify({ choices: [{ delta: {}, finish_reason: 'stop' }], usage: { prompt_tokens: promptTokens, completion_tokens: completionTokens, total_tokens: promptTokens + completionTokens } })}\n\n`)
      res.write('data: [DONE]\n\n')
      res.end()

    } else {
      // Non-streaming: return full JSON response
      const { text, usage } = await generateText({ model, messages, temperature, maxTokens: max_tokens })

      res.json({
        choices: [{ message: { role: 'assistant', content: text }, finish_reason: 'stop' }],
        usage: {
          prompt_tokens: usage?.promptTokens || 0,
          completion_tokens: usage?.completionTokens || 0,
          total_tokens: (usage?.promptTokens || 0) + (usage?.completionTokens || 0)
        },
        model
      })
    }
  } catch (err) {
    console.error('[Gateway Proxy] Error:', err.message)
    res.status(500).json({ error: err.message })
  }
})

app.listen(PORT, () => {
  console.log(`[Gateway Proxy] Vercel AI Gateway proxy running on http://localhost:${PORT}`)
  console.log(`[Gateway Proxy] Python backend → POST http://localhost:${PORT}/v1/chat/completions`)
})
