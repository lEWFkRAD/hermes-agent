from gateway.voice_sentence_queue import VoiceSentenceChunker


def test_first_two_sentences_then_one_at_a_time_across_deltas():
    chunker = VoiceSentenceChunker()

    assert chunker.feed("First sentence. Sec") == []
    assert chunker.feed("ond sentence. Third sentence. ") == [
        "First sentence. Second sentence.",
        "Third sentence.",
    ]
    assert chunker.feed("Fourth sentence! ") == ["Fourth sentence!"]


def test_finish_flushes_a_short_partial_response():
    chunker = VoiceSentenceChunker()

    assert chunker.feed("Only one short response") == []
    assert chunker.finish() == ["Only one short response"]


def test_chunks_never_exceed_provider_limit():
    chunker = VoiceSentenceChunker(first_sentences=1, max_chars=100)
    output = chunker.feed(("word " * 60) + ". ")

    assert output
    assert all(len(chunk) <= 100 for chunk in output)
    assert " ".join(output).replace(" .", ".")
