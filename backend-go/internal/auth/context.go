package auth

import "github.com/gin-gonic/gin"

const actorContextKey = "authenticatedActor"

func SetActor(c *gin.Context, actor Actor) {
	c.Set(actorContextKey, actor)
}

func ActorFromGin(c *gin.Context) (Actor, bool) {
	value, ok := c.Get(actorContextKey)
	if !ok {
		return Actor{}, false
	}
	actor, ok := value.(Actor)
	return actor, ok
}
