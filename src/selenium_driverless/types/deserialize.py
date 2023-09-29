import asyncio
import warnings


class JSRemoteObj:
    def __init__(self, obj_id: str, target):
        super().__init__()
        super().__setattr__("___obj_id__", obj_id)
        super().__setattr__("___target__", target)

    def __repr__(self):
        # noinspection PyUnresolvedReferences
        return f'{self.__class__.__name__}(obj_id={self.__obj_id__}, context_id={self.__context_id__})'

    # noinspection PyUnresolvedReferences
    def __eq__(self, other):
        if isinstance(other, JSRemoteObj) and other.__obj_id__ and self.__obj_id__:
            return other.__obj_id__.split(".")[0] == self.__obj_id__.split(".")[0]
        return super().__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        # noinspection PyUnresolvedReferences
        return hash(f"{self.__obj_id__}{self.__class__}")

    @property
    def __target__(self):
        return self.___target__

    @property
    def __obj_id__(self):
        return self.___obj_id__

    @property
    def __context_id__(self):
        if self.__obj_id__:
            return int(self.__obj_id__.split(".")[1])

    def __obj_id_for_context__(self, context_id: int = None):
        if self.__obj_id__:
            if context_id != self.__context_id__:
                return None
            return self.__obj_id__

    async def __exec_raw__(self, script: str, *args, await_res: bool = False, serialization: str = None,
                           max_depth: int = None, timeout: float = 2, execution_context_id: str = None,
                           unique_context: bool = False):
        """
        example:
        script= "function(...arguments){obj.click()}"
        "const obj" will be the Object according to obj_id
        this is by default globalThis (=> window)
        """
        from selenium_driverless.types import JSEvalException
        from selenium_driverless.types.webelement import WebElement

        if not args:
            args = []
        if not serialization:
            serialization = "deep"

        target = self.__target__

        exec_context = self.__context_id__
        base_obj_id = self.__obj_id__

        if execution_context_id and unique_context:
            warnings.warn("got execution_context_id and unique_context=True, defaulting to execution_context_id")
        if execution_context_id:
            exec_context = execution_context_id
            base_obj_id = None  # enforce execution context id
        elif unique_context:
            # noinspection PyProtectedMember
            exec_context = await target._isolated_context_id
            base_obj_id = None  # enforce execution context id

        _args = []
        for arg in args:
            is_value: bool = True

            if isinstance(arg, JSRemoteObj):
                if isinstance(arg, WebElement):
                    await arg.obj_id  # resolve webelement
                    obj_id = await arg.__obj_id_for_context__(exec_context)
                else:
                    obj_id = arg.__obj_id_for_context__(exec_context)

                if obj_id:
                    is_value = False
                    _args.append({"objectId": obj_id})
                else:
                    warnings.warn("Can't find remote reference of JSRemoteObj, trying to serialize")

            if is_value:
                _args.append({"value": arg})

        ser_opts = {"serialization": serialization, "maxDepth": max_depth,
                    "additionalParameters": {"includeShadowTree": "all", "maxNodeDepth": max_depth}}
        args = {"functionDeclaration": script,
                "arguments": _args, "userGesture": True, "awaitPromise": await_res, "serializationOptions": ser_opts,
                "generatePreview": True}
        if base_obj_id:
            args["objectId"] = base_obj_id
        else:
            args["executionContextId"] = exec_context
        try:
            res = await self.__target__.execute_cdp_cmd("Runtime.callFunctionOn", args, timeout=timeout)
        except Exception as e:
            raise e
        if "exceptionDetails" in res.keys():
            raise JSEvalException(res["exceptionDetails"])
        res = res["result"]
        # noinspection PyProtectedMember
        res = await parse_deep(deep=res.get('deepSerializedValue'), subtype=res.get('subtype'),
                               class_name=res.get('className'), value=res.get("value"),
                               description=res.get("description"), target=target,
                               obj_id=res.get("objectId"), context_id=exec_context, loop=self.__target__._loop)
        return res

    async def __exec__(self, script: str, *args, max_depth: int = 2, serialization: str = None,
                       timeout: float = 2, execution_context_id: str = None,
                       unique_context: bool = None):
        """
        exaple: script = "return elem.click()"
        """
        from selenium_driverless.types.webelement import WebElement

        target = self.__target__
        exec_context = self.__context_id__
        base_obj_id = self.__obj_id__

        if execution_context_id and unique_context:
            warnings.warn("got execution_context_id and unique_context=True, defaulting to execution_context_id")
        if execution_context_id:
            exec_context = execution_context_id
        elif unique_context:
            # noinspection PyProtectedMember
            exec_context = await target._isolated_context_id

        if isinstance(self, WebElement):
            base_obj_id = await self.__obj_id_for_context__(exec_context)

        if exec_context and base_obj_id:
            obj = JSRemoteObj(obj_id=base_obj_id, target=self)
            args = [obj, *args]
            script = """
                (function(...arguments){
                    const obj = arguments.shift()
                    """ + script + "})"
        else:
            script = """
                        (function(...arguments){
                            const obj = this   
                            """ + script + "})"
        res = await self.__exec_raw__(script, *args, max_depth=max_depth,
                                      serialization=serialization, timeout=timeout,
                                      await_res=False, execution_context_id=exec_context)
        return res

    async def __exec_async__(self, script: str, *args, max_depth: int = 2,
                             serialization: str = None, timeout: float = 2,
                             obj_id=None, execution_context_id: str = None,
                             unique_context: bool = False):
        from selenium_driverless.types.webelement import WebElement

        target = self.__target__
        exec_context = self.__context_id__

        if execution_context_id and unique_context:
            warnings.warn("got execution_context_id and unique_context=True, defaulting to execution_context_id")
        if execution_context_id:
            exec_context = execution_context_id
        elif unique_context:
            # noinspection PyProtectedMember
            exec_context = await target._isolated_context_id

        if isinstance(self, WebElement):
            obj_id = await self.__obj_id_for_context__(exec_context)

        if exec_context and obj_id:
            obj = JSRemoteObj(obj_id=obj_id, target=self)
            args = [obj, *args]
            script = """
                (function(...arguments){
                    const obj = arguments.shift()
                    const promise = new Promise((resolve, reject) => {
                                          arguments.push(resolve)
                        });""" + script + ";return promise})"
        else:
            script = """(function(...arguments){
                                   const obj = this
                                   const promise = new Promise((resolve, reject) => {
                                          arguments.push(resolve)
                                    });""" + script + ";return promise})"
        res = await self.__exec_raw__(script, *args, max_depth=max_depth,
                                      serialization=serialization, timeout=timeout,
                                      await_res=True,
                                      execution_context_id=exec_context)
        return res


class JSObject(JSRemoteObj, dict):
    def __init__(self, obj_id: str, target, description: str = None, class_name: str = None,
                 sub_type: str = None):
        JSRemoteObj.__init__(self, obj_id, target)
        dict.__init__(self)
        super().__setattr__("__description__", description)
        super().__setattr__("__class_name__", class_name)
        super().__setattr__("__sub_type__", sub_type)

    def __getattr__(self, k):
        # noinspection PyBroadException
        try:
            return self[k]
        except:
            return self.__getitem__(k)

    def __setattr__(self, k, v):
        self[k] = v

    def __repr__(self):
        return f'{self.__class__.__name__}(description={self.__description__}, sub_type={self.__sub_type__}, class_name={self.__class_name__}, obj_id="{self.__obj_id__}", context_id={self.__context_id__})'

    def __hash__(self):
        # noinspection PyUnresolvedReferences
        return hash(f"{self.__obj_id__}{self.__class__}{self.__context_id__}")


class JSArray(list, JSRemoteObj):
    def __init__(self, obj_id: str, target):
        JSRemoteObj.__init__(self, obj_id, target)

    def __hash__(self):
        # noinspection PyUnresolvedReferences
        return hash(f"{self.__obj_id__}{self.__class__}")


class JSWindow(JSRemoteObj):
    def __init__(self, context: str, obj_id: str, target):
        self.__context__ = context
        JSRemoteObj.__init__(self, obj_id, target)


class JSBigInt(int):
    pass


class JSRegExp(str):
    pass


class JSDate(str):
    pass


class JSSymbol(JSRemoteObj):
    def __init__(self, obj_id: str, target):
        JSRemoteObj.__init__(self, obj_id, target)


class JSFunction(JSRemoteObj):
    def __init__(self, obj_id: str, target, description: str):
        self.__description__ = description
        super().__init__(obj_id, target)

    async def __call__(self, *args, **kwargs):
        # noinspection PyUnresolvedReferences
        return await self.__remote_obj__.execute_script(f"return obj(...arguments)", *args, **kwargs)

    def __repr__(self):
        # noinspection PyUnresolvedReferences
        return f'{self.__class__.__name__}("{self.__description__}", obj_id="{self.__obj_id__}", context_id={self.__context_id__})'


class JSMapException(Exception):
    # from https://stackoverflow.com/a/71705517
    # modified by kaliiiiiiiiii
    pass


class JSMap(dict, JSRemoteObj):
    # from https://stackoverflow.com/a/71705517
    # modified by kaliiiiiiiiii

    def __init__(self, *args, obj_id, target):
        JSRemoteObj.__init__(self, obj_id, target)
        values = [self.__create_element(key, value) for key, value in args]
        self.__values__ = values
        super().__init__()

    def __setitem__(self, key, value):
        self.set(key, value)

    def __getitem__(self, key):
        return self.get(key)

    def __len__(self):
        return len(self.__values__)

    def __delitem__(self, key):
        keys = self.keys()

        if key in keys:
            index = keys.index(key)
            del self.__values__[index]

    def clear(self):
        self.__values__ = []

    def copy(self):
        return self.__values__.copy()

    def has_key(self, k):
        return k in self.keys()

    def update(self, *args, **kwargs):
        if kwargs:
            raise JSMapException(f"no kwargs allowed in '{self.__class__.__name__}.update' method")
        for key, value in args:
            self[key] = value

        return self.__values__

    def __repr__(self) -> str:
        return repr(self.__values__)

    @classmethod
    def __create_element(cls, key, value):
        return {"key": key, "value": value}

    def set(self, key, value):
        keys = self.keys()

        if key in keys:
            index = keys.index(key)
            self.__values__[index] = self.__create_element(key, value)
        else:
            self.__values__.append(self.__create_element(key, value))

        return self.__values__

    def keys(self) -> list:
        return [dict_key_value["key"] for dict_key_value in self.__values__]

    def values(self):
        return [value["value"] for value in self.__values__]

    def items(self):
        return [(dict_key_value["key"], dict_key_value["value"]) for dict_key_value in self.__values__]

    def pop(self, key, default=None):
        keys = self.keys()

        if key in keys:
            index = keys.index(key)
            value = self.__values__.pop(index)["value"]
        else:
            value = default

        return value

    def get(self, key, default=None):
        keys = self.keys()

        if key in keys:
            index = keys.index(key)
            value = self.__values__[index]["value"]
        else:
            value = default

        return value

    def __iter__(self):
        return iter(self.keys())

    def __hash__(self):
        # noinspection PyUnresolvedReferences
        return hash(f"{self.__obj_id__}{self.__class__}")


class JSWeakMap(JSRemoteObj):
    def __init__(self, obj_id: str, target):
        JSRemoteObj.__init__(self, obj_id, target)


class JSSet(JSRemoteObj, set):
    def __init__(self, obj_id: str, target):
        set.__init__(self)
        JSRemoteObj.__init__(self, obj_id, target)


class JSError(JSRemoteObj):
    def __init__(self, obj_id: str, target):
        JSRemoteObj.__init__(self, obj_id, target)


class JSProxy(JSRemoteObj):
    def __init__(self, obj_id: str, target):
        JSRemoteObj.__init__(self, obj_id, target)


class JSPromise(JSRemoteObj):
    def __init__(self, obj_id: str, target):
        JSRemoteObj.__init__(self, obj_id, target)


class JSTypedArray(JSRemoteObj):
    def __init__(self, obj_id: str, target):
        JSRemoteObj.__init__(self, obj_id, target)


class JSArrayBuffer(JSRemoteObj):
    def __init__(self, obj_id: str, target):
        JSRemoteObj.__init__(self, obj_id, target)


class JSIterator(JSFunction):
    def __init__(self, obj_id: str, target, description: str):
        super().__init__(obj_id, target, description=description)


class JSNodeList(JSArray):
    def __init__(self, obj_id: str, target, class_name: str):
        super().__init__(obj_id, target)
        super().__setattr__("__class_name__", class_name)

    def __repr__(self):
        # noinspection PyUnresolvedReferences
        return f'{self.__class__.__name__}("{self.__class_name__}",obj_id={self.__obj_id__}, context_id={self.__context_id__})'


class JSUnserializable(JSRemoteObj):
    def __init__(self, _type, value, target, obj_id: str = None, description: str = None,
                 sub_type: str = None,
                 class_name: str = None):
        super().__init__(obj_id=obj_id, target=target)
        self._value = value
        self._type = _type
        self._description = description
        self._sub_type = sub_type
        self._class_name = class_name

    @property
    def value(self):
        return self._value

    @property
    def type(self):
        return self._type

    @property
    def description(self):
        return self._description

    @property
    def sub_type(self):
        return self._sub_type

    @property
    def class_name(self):
        return self._class_name

    def __repr__(self):
        # noinspection PyUnresolvedReferences
        return f'{self.__class__.__name__}(type="{self.type}",description="{self.description}", sub_type="{self.sub_type}", class_name="{self.class_name}", value={self.value}, obj_id="{self.__obj_id__}", context_id={self.__context_id__})'


async def parse_deep(deep: dict, target, subtype: str = None, class_name: str = None, description: str = None,
                     value=None, obj_id: str = None, loop: asyncio.AbstractEventLoop = None, context_id: str = None):
    from selenium_driverless.types.webelement import WebElement
    from selenium_driverless.sync.webelement import WebElement as SyncWebElement

    if not deep:
        if value is not None:
            return value
        else:
            return JSUnserializable("IdOnly", None, target=target, obj_id=obj_id)

    # special types
    if class_name == 'XPathResult':
        elems = JSNodeList(obj_id=obj_id, target=target, class_name=class_name)
        obj = JSRemoteObj(target=target, obj_id=obj_id)
        res = await obj.__exec__("return obj.resultType == 7", serialization="json")
        if res:
            _len = await obj.__exec__("return obj.snapshotLength", serialization="json")
            for idx in range(_len):
                elems.append(await obj.__exec__("return obj.snapshotItem(arguments[0])", idx,
                                                serialization="deep"))
            return elems
    if class_name in ['NodeList']:
        elems = []
        obj = JSRemoteObj(target=target, obj_id=obj_id)
        for idx in range(int(description[-2])):
            elems.append(await obj.__exec__("return obj[arguments[0]]", idx, serialization="deep",
                                            execution_context_id=context_id))
        return elems

    # structures
    _type = deep.get("type")
    _value = deep.get("value")
    if _type == "array":
        _res = JSArray(obj_id=obj_id, target=target)
        for idx, _deep in enumerate(_value):
            _res.append(await parse_deep(_deep, target))
        return _res
    elif _type == "object":
        _res = JSObject(obj_id=obj_id, target=target, description=description, sub_type=subtype, class_name=class_name)
        for key, value in _value:
            _res.__setattr__(key, await parse_deep(value, target))
        return _res

    # non-json types
    elif _type == "bigint":
        return JSBigInt(_value)
    elif _type == "regexp":
        return JSRegExp(_value["pattern"])
    elif _type == "date":
        return JSDate(_value)
    elif _type == "symbol":
        return JSSymbol(obj_id=obj_id, target=target)
    elif _type == "function":
        return JSFunction(obj_id=obj_id, target=target, description=description)
    elif _type == "map":
        _map = JSMap(obj_id=obj_id, target=target)
        for key, value in _value:
            key = await parse_deep(key, target)
            _map.set(key, await parse_deep(value, target))
        return _map
    elif _type == "set":
        _set = JSSet(obj_id=obj_id, target=target)
        for value in _value:
            value = await parse_deep(value, target)
            _set.add(value)
        return _set
    elif _type == "weakmap":
        return JSWeakMap(obj_id=obj_id, target=target)
    elif _type == "error":
        return JSError(obj_id=obj_id, target=target)
    elif _type == "proxy":
        return JSProxy(obj_id, target=target)
    elif _type == "promise":
        return JSPromise(obj_id, target=target)
    elif _type == "typedarray":
        return JSTypedArray(obj_id, target=target)
    elif _type == "arraybuffer":
        return JSArrayBuffer(obj_id, target=target)
    elif _type == "node":
        if loop:
            return await SyncWebElement(backend_node_id=_value.get('backendNodeId'), target=target, loop=loop,
                                        class_name=class_name, context_id=context_id)
        else:
            return await WebElement(backend_node_id=_value.get('backendNodeId'), target=target, loop=loop,
                                    class_name=class_name, context_id=context_id)
    elif _type == 'htmlcollection':
        _res = JSNodeList(obj_id=obj_id, target=target, class_name=class_name)
        for idx, _deep in enumerate(_value):
            _res.append(await parse_deep(_deep, target))
        return _res
    elif _type == "window":
        return JSWindow(context=_value.get("context"), obj_id=obj_id, target=target)
    elif _type == "generator":
        return JSUnserializable(_type, _value, target=target, obj_id=obj_id,
                                description=description)

    # low-level types
    elif _type in ["number", "string", "boolean"]:
        return _value
    elif _type in ["undefined", "null"]:
        return None

    # non-serializable
    else:
        return JSUnserializable(_type, _value, target=target, obj_id=obj_id, description=description, sub_type=subtype,
                                class_name=class_name)
