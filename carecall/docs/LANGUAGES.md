# English, Russian and Mandarin

CareCall supports English (`en`), Russian (`ru`) and Mandarin Chinese (`zh`). It uses
AssemblyAI Universal-3.6 Pro with automatic language detection and Fish Audio S2.1 Pro
in the budget preset. Existing voice IDs and LLM choices are preserved. The quality
preset retains Gemini and Cartesia, but now also uses AssemblyAI for all three input
languages rather than its English-only Deepgram configuration. No new API keys.

Default: `CARECALL_LANGUAGE=auto`. The initial greeting is English; after the receptionist
speaks, the model replies in that language. Final STT language metadata updates the TTS
language and localized fixed phrases. A language tool handles explicit requests such
as "Can we speak Russian?", including a request made in English. Language interpretation
belongs to the model/provider, not a keyword matcher. Short names/numbers can be ambiguous;
ask explicitly to switch if needed.

## Talk to it

```sh
cd ~/Downloads/take2-voice-starter
lk agent console --input-device "MacBook Pro Microphone" --output-device "MacBook Pro Speakers"
```

Say one of:

* Russian: `Здравствуйте, это регистратура. Давайте говорить по-русски.`
* Mandarin: `您好，这里是预约处。我们可以说普通话吗？`
* English request: `Please speak Russian.` or `Please speak Mandarin Chinese.`

To start directly with a Russian or Mandarin greeting, set `CARECALL_LANGUAGE=ru` or
`CARECALL_LANGUAGE=zh` in your local `.env.local`, then restart. You can also run:

```sh
CARECALL_LANGUAGE=ru lk agent console
CARECALL_LANGUAGE=zh lk agent console
```

This is the initial language, not a restriction on later switching. Recognition remains
multilingual so the receptionist can change languages during the call. `en` starts in
English. Unsupported configuration values fail clearly instead of silently becoming English.

## Receptionist tests

Russian happy path:

1. `Здравствуйте, это Example Family Clinic. Мы принимаем новых пациентов.`
2. `Да, Example Health Example Choice PPO входит в сеть врача Dr Lee по адресу 10 Example Plaza. Направление не требуется.`
3. `Есть время десятого ноября две тысячи двадцать шестого года, с десяти до десяти тридцати утра по времени Нью-Йорка.`
4. Wait for a complete Russian readback. Then: `Да, приём уже записан. Номер подтверждения RU42.`

Mandarin refusal path:

1. `您好，这里是 Example Family Clinic 的预约处。请问患者使用什么保险？`
2. `这个具体保险计划不在我们的网络内。可以自费，费用是二百五十美元。`
3. Expect refusal of self-pay. Then: `请让患者联系保险公司后再给我们打电话。谢谢，再见。`

Switching:

1. Start in English, ask `Please speak Russian.`
2. Ask `Как зовут пациента?` and verify Alex Morgan is preserved.
3. Say `请改用普通话。患者为什么需要预约？` and verify the same routine visit reason.
4. Ask for hold in each language; expect one localized acknowledgement.
5. Interrupt a readback and correct provider/location; expect a new check and review,
   regardless of language. A Russian or Chinese conversation does not imply Moscow or
   Beijing time: calendar comparisons remain in the patient's New York timezone.

Synthetic legal names, insurance/member IDs, confirmation references and addresses stay
verbatim. Natural conversation uses Cyrillic or simplified Chinese, not romanization.
Dates are spoken locally but recorded as ISO datetimes with offsets. Greeting, hold,
silence check-ins and final appointment readback all have explicit translations.
Booking consent, authorization and network checks are identical across languages.

The same voice may retain its original accent when speaking another language. Native
speaker review is still needed for accent, medical vocabulary and pronunciation quality.
Audio tests do not prove every accent or noisy-room condition. No live phone call is
needed for these microphone tests; outbound SIP configuration remains separate.

References: https://docs.livekit.io/agents/models/stt/assemblyai/ and
https://docs.livekit.io/agents/models/tts/fishaudio/ .
