"""
TerminalConsumer — puente WebSocket <-> exec del contenedor (ver SDD 4.4
y flujo 5.2). Al conectar crea un `exec` en el contenedor del usuario y
hace el hijack; después solo reenvía bytes en ambas direcciones.
"""

import asyncio
import contextlib
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from . import docker_client
from .models import Instance


class TerminalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.exec_socket = None
        self.reader_task = None
        self.shutting_down = False

        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return

        instance = await self._get_instance(user)
        if instance is None:
            await self.close(code=4004)
            return

        self.instance_id = instance.id

        try:
            self.exec_id = await asyncio.to_thread(
                docker_client.create_exec, instance.container_id
            )
            self.exec_socket = await asyncio.to_thread(
                docker_client.start_exec_hijacked, self.exec_id
            )
        except docker_client.DockerClientError:
            await self.close(code=4002)
            return

        await self.accept()
        self.reader_task = asyncio.create_task(self._pump_docker_to_ws())

    async def disconnect(self, close_code):
        """
        El orden importa: primero se cierra el socket del exec, lo que
        desbloquea al hilo parado en `recv()`, y recién después se espera
        a que la tarea lectora termine. Si se cancelara la tarea sin
        esperarla, ese hilo seguiría vivo con un descriptor que el kernel
        ya podría haber reasignado a la siguiente sesión — y la nueva
        consola se caería sola a los pocos segundos.
        """
        self.shutting_down = True

        if self.exec_socket is not None:
            await asyncio.to_thread(self.exec_socket.close)

        if self.reader_task is not None:
            self.reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader_task

    async def receive(self, text_data=None, bytes_data=None):
        """
        Los frames binarios son tecleo del usuario y se reenvían tal cual
        al exec. Los frames de texto son mensajes de control en JSON
        (por ahora solo `resize`), no datos para el proceso.
        """
        if self.exec_socket is None:
            return

        if text_data is not None:
            await self._handle_control(text_data)
            return

        await asyncio.to_thread(self.exec_socket.send, bytes_data)
        await self._touch_activity()

    async def _handle_control(self, text_data):
        message = json.loads(text_data)
        if message.get("type") != "resize":
            return
        try:
            await asyncio.to_thread(
                docker_client.resize_exec,
                self.exec_id,
                int(message["rows"]),
                int(message["cols"]),
            )
        except docker_client.DockerClientError:
            # El resize es best-effort: si llega antes de que el exec esté
            # listo, la consola sigue siendo usable con el tamaño previo.
            pass

    async def _pump_docker_to_ws(self):
        """Lee del socket hijacked y reenvía al navegador hasta que se corte."""
        try:
            while True:
                chunk = await asyncio.to_thread(self.exec_socket.recv, 4096)
                if not chunk:
                    break
                await self.send(bytes_data=chunk)
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            # Si ya estamos cerrando por desconexión del navegador, el
            # WebSocket se está yendo solo; cerrarlo otra vez sobra.
            if not self.shutting_down:
                await self.close()

    @database_sync_to_async
    def _get_instance(self, user):
        return Instance.objects.filter(user=user).first()

    @database_sync_to_async
    def _touch_activity(self):
        Instance.objects.filter(id=self.instance_id).update(last_activity=timezone.now())
