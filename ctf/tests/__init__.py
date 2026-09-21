"""
Suite de pruebas automatizadas de la plataforma CTF.

Ninguna prueba de este paquete necesita Docker: las llamadas al motor de
contenedores se sustituyen por dobles de prueba (`unittest.mock`), de modo
que la suite corre en cualquier maquina y en integracion continua.

Las pruebas que SI requieren Docker (humo, estres y carga) viven en
`pruebas/` como scripts ejecutables, porque miden el sistema real.
"""
