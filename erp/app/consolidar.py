"""Consolidação financeira de todas as empresas, para rodar por cron: python -m app.consolidar"""
from .services.agendador import rodar_pendentes

if __name__ == "__main__":
    feitas = rodar_pendentes()
    print(f"Consolidação agendada: {len(feitas)} empresa(s) processada(s)")
