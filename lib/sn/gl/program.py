import collections, re, sys
from collections import defaultdict
import numpy as np

from PyQt5 import QtGui, QtOpenGL, QtWidgets
from OpenGL.GL import *
from OpenGL.GL.shaders import *

#from .util import *
from . import debug
from .globject import _GLObject_
from ..qt.application import Application

class Program(_GLObject_):
    shadertypes = dict(
            vs       = GL_VERTEX_SHADER,
            vert     = GL_VERTEX_SHADER,
            vertex   = GL_VERTEX_SHADER,
            tcs      = GL_TESS_CONTROL_SHADER,
            tesscontrol
                     = GL_TESS_CONTROL_SHADER,
            tessellationcontrol
                     = GL_TESS_CONTROL_SHADER,
            tes      = GL_TESS_EVALUATION_SHADER,
            tesseval = GL_TESS_EVALUATION_SHADER,
            tessevaluation
                     = GL_TESS_EVALUATION_SHADER,
            tessellationevaluation
                     = GL_TESS_EVALUATION_SHADER,
            gs       = GL_GEOMETRY_SHADER,
            geometry = GL_GEOMETRY_SHADER,
            fs       = GL_FRAGMENT_SHADER,
            fragment = GL_FRAGMENT_SHADER,
            cs       = GL_COMPUTE_SHADER,
            compute  = GL_COMPUTE_SHADER)

    def create(self, path):
        self._load(path)
        self._create()
        self._compileLink()
        self._validate()
        self._examineVariables()
        self._examineUniforms()
        self._examineUniformBlocks()

    def delete(self):
        if self._program and bool(glDeleteProgram):
            p = self._program; self._program = None
            glDeleteProgram(p)

    def _load(self, path):
        shadertypes = self.shadertypes
        shaderset = []
        kind = None; code = []
        with open(path, 'r') as f:
            for line in f:
                k = ''.join(line.strip('#\n').split(' ')).lower().replace('shader', '')
                if k in shadertypes.keys():
                    if kind != None:
                        shaderset.append((kind, ''.join(code)))
                    kind = shadertypes[k]; code = []
                else:
                    code.append(line)
        if kind != None:
            shaderset.append((kind, ''.join(code)))
        self._shaderset = shaderset

    def _create(self):
        self._program = glCreateProgram()
        self._validated = self._linked = False
        self._variables = dict(vertex=set(), uniform=set())
        self._samplers = {}
        self._known_invalid = set()

    def _compileLink(self):
        self._linked = False
        program = self._program
        shaderlist = []
        for t, code in self._shaderset:
            print('Compiling a shader: {0}\n'.format(t))
            shader = glCreateShader(t)
            shaderlist.append(shader)
            glShaderSource(shader, code)
            glCompileShader(shader)
            if glGetShaderiv(shader, GL_COMPILE_STATUS) != GL_TRUE:
                errors = str(glGetShaderInfoLog(shader), 'utf-8')
                msg = self._get_error(code, errors, 4)
                raise RuntimeError('Shader compilation failure error in {0}:\n{1}'
                        .format(t, msg))
            glAttachShader(program, shader)

        glLinkProgram(program)
        if glGetProgramiv(program, GL_LINK_STATUS) != GL_TRUE:
            errors = glGetProgramInfoLog(program)
            if len(errors) > 0:
                errors = errors.decode('utf-8')
            raise RuntimeError('Program linking error:\n{0}'.format(errors))
        for shader in shaderlist:
            glDetachShader(program, shader)
            glDeleteShader(shader)
        self._linked = True

    def _validate(self):
        self._validated = True
        glValidateProgram(self._program)
        if glGetProgramiv(self._program, GL_VALIDATE_STATUS) != GL_TRUE:
            raise RuntimeError('Program validation error:\n{0}'
                    .format(glGetProgramInfoLog(self._program).decode('utf-8')))

    def _get_error(self, code, errors, indentation=0):
        results = []
        lines = None
        if code is not None:
            lines = [line.strip() for line in code.split('\n')]

        for error in errors.split('\n'):
            #error = error.split()
            if not error:
                continue

            lineno, error = self._parse_error(error)
            if None in (lineno, lines):
                results.append(str(error))
            else:
                results.append('on line {0}: {1}'.format(lineno, error))
                if lineno > 0 and lineno < len(lines):
                    results.append('  {0}'.format(lines[lineno - 1]))
        results = [' ' * indentation + r for r in results]
        return '\n'.join(results)

    def _parse_error(self, error):
        error = str(error)
        # Nvidia
        # 0(7): error C1008: undefined variable "MV"
        m = re.match(r'(\d+)\((\d+)\)\s*:\s(.*)', error)
        if m:
            return int(m.group(2)), m.group(3)
        # ATI / Intel
        # ERROR: 0:131: '{' : syntax error parse error
        m = re.match(r'ERROR:\s(\d+):(\d+):\s(.*)', error)
        if m:
            return int(m.group(2)), m.group(3)
        # Nouveau
        # 0:28(16): error: syntax error, unexpected ')', expecting '('
        m = re.match(r'(\d+):(\d+)\((\d+)\):\s(.*)', error)
        if m:
            return int(m.group(2)), m.group(4)
        # Other ...
        return None, error

    def _examineVariables(self):
        self._examineAttributes()

    from OpenGL.arrays import buffers

    vertexAttribHandler = dict()
    vertexAttribHandler[GL_FLOAT_VEC2] = glVertexAttrib2f
    vertexAttribHandler[GL_FLOAT_VEC3] = glVertexAttrib3f
    vertexAttribHandler[GL_FLOAT_VEC4] = glVertexAttrib4f

    def _examineAttributes(self):
        program = self._program

        n = np.zeros(1, dtype=np.int32)
        glGetProgramInterfaceiv(program, GL_PROGRAM_INPUT, GL_ACTIVE_RESOURCES, n)
        if debug._logOnShaderVariables_:
            print('#attributes = {0}'.format(n[0]))

        types = list(self.vertexAttribHandler.keys())
        properties = np.array([ GL_NAME_LENGTH, GL_TYPE, GL_LOCATION ])

        bbuf = bytes(256)
        info = np.zeros(3, dtype=np.int32)
        length = np.zeros(1, dtype=np.int32)
        a = self.a = dict()
        for attr in range(n[0]):
            glGetProgramResourceiv(program, GL_PROGRAM_INPUT, attr,
                    3, properties, 3, length, info)
            # print('length = {0}, info = {1}'.format(length, info))
            glGetProgramResourceName(program, GL_PROGRAM_INPUT, attr, len(bbuf), length, bbuf)
            location = info[2]
            if location == -1: continue
            name = bbuf[:length].decode('utf-8')
            typestr = types[types.index(info[1])].__repr__()
            if debug._logOnShaderVariables_:
                print('attribute {0}:{1}@{2}'.format(name, typestr, location))
            f = self.vertexAttribHandler[info[1]]
            a[name] = (lambda *args, f=f, l=location: f(*([l] + list(args))))
            a[name].name = name; a[name].loc = location

    uniformHandler = dict()

    def _glUniformv_(f, loc, name, v):
        if debug._logOnSetUniform_:
            print('Uniform[{0}]: {1}\n'.format(name, v))
        f(loc, *v)

    def _glUniformfv_(f, loc, name, V):
        if debug._logOnSetUniform_:
            print('Uniform[{0}]: {1}\n'.format(name, V))
        f(loc, *V)

    def _uniformv_(f): return lambda loc, name, v: Program._glUniformv_(f, loc, name, v)
    def _uniformfv_(f): return lambda loc, name, *V: Program._glUniformfv_(f, loc, name, V)

    uniformHandler[GL_INT]        = _uniformv_(glUniform1i)
    uniformHandler[GL_INT_VEC2]   = _uniformv_(glUniform2i)
    uniformHandler[GL_INT_VEC3]   = _uniformv_(glUniform3i)
    uniformHandler[GL_INT_VEC4]   = _uniformv_(glUniform4i)
    uniformHandler[GL_FLOAT]      = _uniformfv_(glUniform1f)
    uniformHandler[GL_FLOAT_VEC2] = _uniformfv_(glUniform2f)
    uniformHandler[GL_FLOAT_VEC3] = _uniformfv_(glUniform3f)
    uniformHandler[GL_FLOAT_VEC4] = _uniformfv_(glUniform4f)

    def _glUniformMatrix_(f, loc, name, M):
        if debug._logOnSetUniform_: print('Uniform[{0}]:\n{1}\n'.format(name, M))
        f(loc, 1, GL_FALSE, M.T)  # Row-major --> Column-major conversion
#       f(loc, 1, GL_FALSE, M)

#   def umatrix(f): return lambda loc, M: f(loc, 1, GL_FALSE, M.T)
    def _uniformMatrix_(f): return lambda loc, name, M: Program._glUniformMatrix_(f, loc, name, M)
    def _uniformMatrixIgnored_(): return lambda *args: None

    uniformHandler[GL_FLOAT_MAT2] = glUniformMatrix2fv
    uniformHandler[GL_FLOAT_MAT3] = glUniformMatrix3fv
    uniformHandler[GL_FLOAT_MAT4] = _uniformMatrix_(glUniformMatrix4fv)
    uniformHandler[GL_FLOAT_MAT2x3] = glUniformMatrix2x3fv

    uniformHandler[GL_FLOAT_MAT2x4] = glUniformMatrix2x4fv
    uniformHandler[GL_FLOAT_MAT3x2] = glUniformMatrix3x2fv
    uniformHandler[GL_FLOAT_MAT3x4] = glUniformMatrix3x4fv
    uniformHandler[GL_FLOAT_MAT4x2] = glUniformMatrix4x2fv
    uniformHandler[GL_FLOAT_MAT4x3] = glUniformMatrix4x3fv

    def _examineUniforms(self):
        p = self._program

        ibuf = np.zeros(5, dtype=np.int32)
        bbuf = bytes(256)

        glGetProgramInterfaceiv(p, GL_UNIFORM, GL_ACTIVE_RESOURCES, ibuf)
        n = ibuf[0]

        types = list(self.uniformHandler.keys())
        properties = np.array([ GL_NAME_LENGTH, GL_TYPE, GL_LOCATION, GL_BLOCK_INDEX ])
        u = self.u = defaultdict(lambda: lambda *args: None)
        if debug._logOnShaderVariables_:
            print('#uniforms = {0}'.format(n))
        for i in range(n):
            glGetProgramResourceiv(p, GL_UNIFORM, i, len(properties), properties,
                    len(ibuf), ibuf[len(properties):], ibuf)
            loc = ibuf[2]
            if loc == -1: continue

            # print("loc = {0}, len = {1}, type = {2}".format(loc, ibuf[0], ibuf[1]))
            length = ibuf[0] + 1
            _t = ibuf[1]
            t = types[types.index(ibuf[1])].__repr__()
            # print('length = {0}, type = {1}, location = {2}' .format(length, t, loc))

            glGetProgramResourceName(p, GL_UNIFORM, i, len(bbuf), ibuf[:1], bbuf)
            length = ibuf[0]
            name = bbuf[:length].decode('utf-8')
            if debug._logOnShaderVariables_:
                print('uniform {0}:{1}@{2}'.format(name, t, loc))
            f = self.uniformHandler[_t]
            u[name] = (lambda *args, f=f, loc=loc, name=name: f(*([loc, name] + list(args))))
            u[name].name = name; u[name].loc = loc
        # print(u)

    def _examineUniformBlocks(self):
        pass

    def use(self):
        glUseProgram(self._program)
