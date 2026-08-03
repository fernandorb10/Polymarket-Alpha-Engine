import type { Settings } from "./config";

export async function notify(settings: Settings, message: string): Promise<boolean> {
  if (!settings.telegramBotToken || !settings.telegramChatId) return false;
  const url = `https://api.telegram.org/bot${settings.telegramBotToken}/sendMessage`;
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        chat_id: settings.telegramChatId,
        text: message.slice(0, 4000),
        disable_web_page_preview: "true",
      }),
      signal: AbortSignal.timeout(10000),
    });
    const body = (await response.json()) as { ok?: boolean };
    return Boolean(body.ok);
  } catch {
    return false;
  }
}
