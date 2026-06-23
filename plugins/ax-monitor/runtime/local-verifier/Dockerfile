FROM python:3.12-slim

WORKDIR /app

# 외부 의존 없음(stdlib only) — requirements.txt 는 자리표시자.
COPY requirements.txt .

COPY main.py transcript.py ./

EXPOSE 14210
# 컨테이너에서는 captures 를 볼륨으로 마운트하면 호스트에서 바로 확인 가능:
#   docker run -p 14210:14210 -v "$PWD/captures:/app/captures" ax-local-verifier
CMD ["python", "main.py"]
